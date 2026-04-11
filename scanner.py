import os
import re
import threading
import time

try:
    import pwd
except ImportError:
    pwd = None  # Not available on Windows
from concurrent.futures import ThreadPoolExecutor

class FileScanner:
    def __init__(self, config=None):
        self.config = config or {}
        self.extensions = set(self.config.get("extensions", [".mov", ".exr", ".png", ".mp4", ".jpg", ".jpeg", ".dpx", ".tiff", ".tif"]))
        self.ignore_dirs = set(self.config.get("ignore_dirs", [".git", ".svn", "__pycache__", "thumbnail.jpg", "rendergallery"]))
        self.non_sequence_extensions = set(self.config.get("non_sequence_extensions", [".mov", ".mp4"]))
        self.version_regex = re.compile(self.config.get("version_regex", r"[._]v(\d+)|v(\d+)"))
        self.max_workers = self.config.get("thread_count", 4)
        self.max_depth = self.config.get("max_depth", 25)
        self.bundle_sequences = self.config.get("bundle_sequences", True)
        
        self.cancel_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
    def get_owner(self, st):
        if pwd:
            try:
                return pwd.getpwuid(st.st_uid).pw_name
            except (KeyError, AttributeError):
                return str(st.st_uid)
        return "unknown"

    def format_size_str(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        
        size_name = ("B", "KB", "MB", "GB", "TB", "PB")
        i = 0
        p = float(size_bytes)
        
        while i < len(size_name) - 1 and p >= 1024:
            p /= 1024.0
            i += 1
            
        return f"{p:.2f} {size_name[i]}"

    def scan(self, start_path, callback=None):
        self.cancel_event.clear()
        
        from collections import deque
        from concurrent.futures import wait, FIRST_COMPLETED

        queue = deque([(start_path, 1.0, 0)])
        futures = set()
        all_items = []
        
        total_progress = 0.0
        scanned_count = 0
        last_update = time.time()
        recent_scanned_dirs = []
        
        def schedule_next():
            while queue and len(futures) < self.max_workers:
                path, weight, depth = queue.popleft()
                futures.add(self.executor.submit(self._scan_and_process_worker, path, start_path, weight, depth))

        schedule_next()
        
        while (futures or queue) and not self.cancel_event.is_set():
            done, _ = wait(futures, timeout=0.05, return_when=FIRST_COMPLETED)
            
            for f in done:
                futures.remove(f)
                try:
                    subdirs, items, weight, depth, scanned_path = f.result()
                    
                    if items:
                        all_items.extend(items)
                        scanned_count += len(items)
                    
                    recent_scanned_dirs.append(scanned_path)
                        
                    if callback and items:
                        callback(items, {"scanned": scanned_count, "progress": total_progress * 100, "phase": "scanning", "scanned_dirs": []})
                    
                    if subdirs and depth < self.max_depth:
                        if len(subdirs) > 0:
                            child_weight = weight / len(subdirs)
                            for d in subdirs:
                                queue.append((d, child_weight, depth + 1))
                    else:
                        total_progress += weight
                        
                except Exception as e:
                    print(f"Scan error: {e}")
            
            schedule_next()
            
            if time.time() - last_update > 0.2:
                 if callback:
                     callback([], {
                         "scanned": scanned_count, 
                         "progress": min(100, int(total_progress * 100)), 
                         "phase": "scanning",
                         "scanned_dirs": list(recent_scanned_dirs)
                     })
                     recent_scanned_dirs = []
                 last_update = time.time()

        if self.cancel_event.is_set():
            for f in futures:
                f.cancel()
            return all_items
            
        if callback:
            callback([], {"scanned": scanned_count, "progress": 100, "phase": "complete", "scanned_dirs": list(recent_scanned_dirs)})
            
        return all_items

    def _scan_and_process_worker(self, path, root_path, weight, depth):
        subdirs = []
        raw_files = []
        
        if self.cancel_event.is_set():
            return [], [], weight, depth, path

        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if self.cancel_event.is_set():
                        break
                    
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in self.ignore_dirs and not entry.name.startswith('.'):
                            subdirs.append(entry.path)
                            try:
                                raw_files.append((entry.path, entry.name, entry.stat(), True))
                            except OSError:
                                pass
                    elif entry.is_file():
                        if entry.name in self.ignore_dirs:
                            continue
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in self.extensions:
                            try:
                                raw_files.append((entry.path, entry.name, entry.stat(), False))
                            except OSError:
                                pass
        except OSError:
            pass
            
        items = self._process_files(raw_files, root_path)
        return subdirs, items, weight, depth, path

    def _process_files(self, raw_files, start_path):
        final_items = []
        sequence_candidate_files = []
        
        if not self.bundle_sequences:
            for p, name, st, is_dir in raw_files:
                if is_dir:
                    final_items.append(self._make_item(p, name, st, start_path, is_directory=True))
                else:
                    final_items.append(self._make_item(p, name, st, start_path))
            return self._group_versions(final_items)

        for p, name, st, is_dir in raw_files:
            if is_dir:
                 final_items.append(self._make_item(p, name, st, start_path, is_directory=True))
                 continue
                 
            ext = os.path.splitext(name)[1].lower()
            if ext in self.non_sequence_extensions:
                final_items.append(self._make_item(p, name, st, start_path))
            else:
                sequence_candidate_files.append((p, name, st))

        groups = {}
        frame_regex = re.compile(r"^(.*?)([._ ]?)(\d+)(\.[^.]+)$")
        singles = []
        
        for p, name, st in sequence_candidate_files:
            match = frame_regex.match(name)
            if match:
                prefix, sep, frame_str, ext = match.groups()
                key = (os.path.dirname(p), prefix, sep, ext)
                if key not in groups:
                    groups[key] = []
                groups[key].append({
                    "path": p,
                    "name": name,
                    "frame": int(frame_str),
                    "frame_str": frame_str,
                    "stat": st
                })
            else:
                singles.append((p, name, st))
        
        for key, files in groups.items():
            if len(files) > 1:
                files.sort(key=lambda x: x["frame"])
                
                dirname, prefix, sep, ext = key
                first_f = files[0]
                last_f = files[-1]
                
                pad_len = len(first_f["frame_str"])
                padding = "#" * pad_len
                name = f"{prefix}{sep}{padding}{ext}"
                
                first_frame = files[0]['frame']
                last_frame = files[-1]['frame']
                frames = f"{first_frame}-{last_frame}"
                
                total_size = sum(f["stat"].st_size for f in files)
                max_mtime = max(f["stat"].st_mtime for f in files)
                owner = self.get_owner(first_f["stat"])
                
                brace_pad = f"%0{pad_len}d"
                seq_path = f"{dirname}/{prefix}{sep}{brace_pad}{ext}".replace("\\", "/")
                
                item = {
                    "name": name,
                    "path": seq_path,
                    "relpath": os.path.relpath(first_f["path"], start_path).replace("\\", "/"),
                    "type": "Sequence",
                    "frames": frames,
                    "first_frame": first_frame,
                    "last_frame": last_frame,
                    "size": total_size,
                    "size_str": self.format_size_str(total_size),
                    "date": max_mtime,
                    "owner": owner,
                    "extension": ext,
                    "is_sequence": True,
                    "is_folder": False
                }
                dir_rel = os.path.relpath(dirname, start_path).replace("\\", "/")
                if dir_rel == ".":
                    item["relpath"] = name
                else:
                    item["relpath"] = f"{dir_rel}/{name}"
                    
                final_items.append(item)
            else:
                f = files[0]
                singles.append((f["path"], f["name"], f["stat"]))
        
        for p, name, st in singles:
            final_items.append(self._make_item(p, name, st, start_path))

        return self._group_versions(final_items)

    def _make_item(self, path, name, st, start_path, is_directory=False):
        return {
            "name": name,
            "path": path,
            "relpath": os.path.relpath(path, start_path).replace("\\", "/"),
            "type": "Folder" if is_directory else "File",
            "frames": "" if is_directory else "1",
            "size": 0 if is_directory else st.st_size,
            "size_str": "" if is_directory else self.format_size_str(st.st_size),
            "date": st.st_mtime,
            "owner": self.get_owner(st),
            "extension": "" if is_directory else os.path.splitext(name)[1],
            "is_sequence": False,
            "is_folder": is_directory
        }

    def _group_versions(self, items):
        groups = {}
        ungrouped = []
        
        for item in items:
            name = item["name"]
            match = self.version_regex.search(name)
            if match:
                v_str = None
                for g in match.groups():
                    if g is not None:
                        v_str = g
                        break
                
                if v_str is not None:
                    v_num = int(v_str)
                    span = match.span()
                    prefix = name[:span[0]]
                    suffix = name[span[1]:]
                    key = (prefix, suffix)
                    
                    if key not in groups:
                        groups[key] = []
                    
                    item["version"] = v_num
                    groups[key].append(item)
                else:
                    ungrouped.append(item)
            else:
                ungrouped.append(item)
        
        final_output = list(ungrouped)
        
        for key, group_items in groups.items():
            group_items.sort(key=lambda x: x["version"], reverse=True)
            for i, item in enumerate(group_items):
                item["is_latest_version"] = (i == 0)
                item["version_rank"] = i
                item["version_group"] = str(key)
                final_output.append(item)
                
        final_output.sort(key=lambda x: x["name"])
        return final_output

    def stop(self):
        self.cancel_event.set()
