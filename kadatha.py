# Kadatha - File broswer for nuke
# version 1.5.0

import os
import sys
import threading
import datetime
import time
import subprocess
import shutil

try:
    from PySide6 import QtWidgets, QtCore, QtGui
except ImportError:
    print("PySide6 is not available. Please run inside Nuke 15 or install PySide6.")
    # Fallback to PySide2 if needed, though PySide6 was requested.
    try:
        from PySide2 import QtWidgets, QtCore, QtGui
    except ImportError:
        pass

try:
    import nuke
    import nukescripts
except ImportError:
    nuke = None
    nukescripts = None

import json

import scanner
from scanner import FileScanner

import queue
import hashlib
import tempfile

def load_config_at_import():
    config_path = os.path.expanduser("~/.nuke/Kadatha_config.json")
    old_path = os.path.join(os.path.dirname(__file__), "config.json")
    found_path = None
    if os.path.exists(config_path):
        found_path = config_path
    elif os.path.exists(old_path):
        found_path = old_path
    if found_path:
        try:
            with open(found_path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def resolve_executable_path(name, config=None):
    if not config:
        config = load_config_at_import()
        
    # 1. Check config ffmpeg_dir
    ffmpeg_dir = config.get("ffmpeg_dir")
    if ffmpeg_dir and os.path.exists(ffmpeg_dir):
        candidates = [
            os.path.join(ffmpeg_dir, name),
            os.path.join(ffmpeg_dir, f"{name}.exe"),
            os.path.join(ffmpeg_dir, "bin", name),
            os.path.join(ffmpeg_dir, "bin", f"{name}.exe")
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.normpath(c).replace('\\', '/')

    # 2. Check env variables
    env_name_path = os.environ.get(f"{name.upper()}_PATH")
    if env_name_path and os.path.isfile(env_name_path):
        return os.path.normpath(env_name_path).replace('\\', '/')
        
    for env_key in ["FFMPEG_DIR", "FFMPEG_BIN"]:
        env_dir = os.environ.get(env_key)
        if env_dir and os.path.exists(env_dir):
            candidates = [
                os.path.join(env_dir, name),
                os.path.join(env_dir, f"{name}.exe"),
                os.path.join(env_dir, "bin", name),
                os.path.join(env_dir, "bin", f"{name}.exe")
            ]
            for c in candidates:
                if os.path.isfile(c):
                    return os.path.normpath(c).replace('\\', '/')

    # 3. Check system standard PATH
    resolved = shutil.which(name)
    if not resolved:
        return None
        
    resolved = os.path.normpath(resolved).replace('\\', '/')
    # If on Windows and resolved to a .bat/.cmd, try to parse it
    if os.name == 'nt' and resolved.lower().endswith(('.bat', '.cmd')):
        try:
            with open(resolved, 'r', errors='ignore') as f:
                content = f.read()
            # Try to find an absolute path ending in .exe
            import re
            m = re.search(r'([A-Za-z]:[^\s"]+\.exe|"[A-Za-z]:[^\s"]+\.exe")', content)
            if m:
                exe_path = m.group(1).strip('"')
                if os.path.exists(exe_path):
                    return exe_path
        except Exception:
            pass
            
    return resolved

FFMPEG_PATH = None
FFPROBE_PATH = None

def resolve_ffmpeg_paths(config=None):
    global FFMPEG_PATH, FFPROBE_PATH
    FFMPEG_PATH = resolve_executable_path("ffmpeg", config)
    FFPROBE_PATH = resolve_executable_path("ffprobe", config)

# Initial resolution at import time
resolve_ffmpeg_paths()

def check_ffmpeg_available():
    return FFMPEG_PATH is not None

def get_cache_paths(path):
    temp_dir = tempfile.gettempdir()
    cache_dir = os.path.join(temp_dir, "Kadatha_Cache", "previews")
    if not os.path.exists(cache_dir):
        try:
            os.makedirs(cache_dir)
        except Exception:
            pass
    h = hashlib.md5(path.encode('utf-8', errors='ignore')).hexdigest()
    single_path = os.path.join(cache_dir, f"{h}_single.png")
    strip_path = os.path.join(cache_dir, f"{h}_strip.png")
    return single_path, strip_path

def is_cache_valid(cache_path, source_mtime):
    if not os.path.exists(cache_path):
        return False
    if not source_mtime:
        return True
    try:
        return os.path.getmtime(cache_path) >= source_mtime
    except Exception:
        return False

def get_video_frame_count(path):
    if not FFPROBE_PATH:
        return 100
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames",
            "-of", "default=nokey=1:noprint_wrappers=1",
            path
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        out, _ = proc.communicate()
        val = out.decode(errors='ignore').strip()
        if val and val.isdigit():
            return int(val)
        
        # Fallback to duration and r_frame_rate
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration:stream=r_frame_rate",
            "-of", "default=nokey=1:noprint_wrappers=1",
            path
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        out, _ = proc.communicate()
        lines = [l.strip() for l in out.decode(errors='ignore').splitlines() if l.strip()]
        if len(lines) >= 2:
            duration = float(lines[0])
            fps_str = lines[1]
            if '/' in fps_str:
                num, den = fps_str.split('/')
                fps = float(num) / float(den)
            else:
                fps = float(fps_str)
            return max(1, int(duration * fps))
    except Exception as e:
        print(f"ffprobe error: {e}")
    return 100 # Default fallback


# Initialize Icons
ICONS_DIR = os.path.join(os.path.dirname(__file__), "Icons")
FILE_ICON = QtGui.QIcon(os.path.join(ICONS_DIR, "file.png"))
FOLDER_ICON = QtGui.QIcon(os.path.join(ICONS_DIR, "folder.png"))
STAR_ICON = QtGui.QIcon(os.path.join(ICONS_DIR, "star.png"))

class FileTableModel(QtCore.QAbstractTableModel):
    def __init__(self, data=None, parent=None):
        super(FileTableModel, self).__init__(parent)
        self._data = data or []
        self._headers = ["Name", "Version", "Frames", "Owner", "Date", "Size"]
        self._keys = ["name", "version", "frames", "owner", "date", "size_str"]

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self._headers)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        
        item = self._data[index.row()]
        col = index.column()
        
        if role == QtCore.Qt.DisplayRole:
            key = self._keys[col]
            val = item.get(key, "")
            if key == "date" and val:
                try:
                    return datetime.datetime.fromtimestamp(val).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    return str(val)
            if key == "version" and val is not None:
                try:
                    return f"v{int(val):03d}"
                except (ValueError, TypeError):
                    return f"v{val}"
            return str(val)

        elif role == QtCore.Qt.UserRole:
            return item

        elif role == QtCore.Qt.DecorationRole:
            if col == 0:
                if item.get("is_favorite"):
                    return STAR_ICON
                elif item.get("is_folder"):
                    return FOLDER_ICON
                else:
                    return FILE_ICON
                
        elif role == QtCore.Qt.ForegroundRole:
            if item.get("imported_node_name") or item.get("has_imported"):
                return QtGui.QColor(255, 165, 0)
                
        elif role == QtCore.Qt.ToolTipRole:
            path = item.get("path", "")
            if item.get("is_sequence"):
                return f"Sequence: {path}\nFrames: {item.get('frames', '')}"
            return path
                
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal:
            if role == QtCore.Qt.DisplayRole:
                return self._headers[section]
            if role == QtCore.Qt.ToolTipRole:
                tooltips = [
                    "File or sequence name",
                    "Version number extracted from path",
                    "Frame range (for sequences)",
                    "File owner/user",
                    "Last modified date",
                    "File or sequence size"
                ]
                if 0 <= section < len(tooltips):
                    return tooltips[section]
        return None

    def flags(self, index):
        default_flags = super(FileTableModel, self).flags(index)
        if index.isValid():
            return default_flags | QtCore.Qt.ItemIsDragEnabled
        return default_flags

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        mime_data = QtCore.QMimeData()
        urls = []
        rows = set()
        for index in indexes:
            if index.row() not in rows:
                rows.add(index.row())
                item = self._data[index.row()]
                path = item.get("path")
                if path:
                    urls.append(QtCore.QUrl.fromLocalFile(path))
        mime_data.setUrls(urls)
        return mime_data

    def update_data(self, new_data):
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()

class FileTreeItem:
    def __init__(self, data, is_root=False, parent=None):
        self._data = data or {}
        self._parent = parent
        self._children = []
        self._is_root = is_root
        
    def appendChild(self, item):
        self._children.append(item)
        
    def child(self, row):
        if 0 <= row < len(self._children):
            return self._children[row]
        return None
        
    def childCount(self):
        return len(self._children)
        
    def row(self):
        if self._parent:
            try:
                return self._parent._children.index(self)
            except ValueError:
                return 0
        return 0
        
    def parentItem(self):
        return self._parent

class FileTreeModel(QtCore.QAbstractItemModel):
    def __init__(self, data=None, parent=None):
        super(FileTreeModel, self).__init__(parent)
        self.root_item = FileTreeItem(None, is_root=True)
        self._headers = ["Name", "Version", "Frames", "Owner", "Date", "Size"]
        self._keys = ["name", "version", "frames", "owner", "date", "size_str"]
        if data:
            self.update_data(data)

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()
        return parent_item.childCount()

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self._headers)

    def index(self, row, column, parent=QtCore.QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()
            
        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()
            
        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QtCore.QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QtCore.QModelIndex()
            
        child_item = index.internalPointer()
        parent_item = child_item.parentItem()
        
        if parent_item == self.root_item or parent_item is None:
            return QtCore.QModelIndex()
            
        return self.createIndex(parent_item.row(), 0, parent_item)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        
        node = index.internalPointer()
        item = node._data
        col = index.column()
        
        if role == QtCore.Qt.DisplayRole:
            key = self._keys[col]
            val = item.get(key, "")
            if key == "date" and val:
                try:
                    return datetime.datetime.fromtimestamp(val).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    return str(val)
            if key == "version" and val is not None:
                try:
                    return f"v{int(val):03d}"
                except (ValueError, TypeError):
                    return f"v{val}"
            return str(val)

        elif role == QtCore.Qt.UserRole:
            return item

        elif role == QtCore.Qt.DecorationRole:
            if col == 0:
                if item.get("is_favorite"):
                    return STAR_ICON
                elif item.get("is_folder"):
                    return FOLDER_ICON
                else:
                    return FILE_ICON
                
        elif role == QtCore.Qt.ForegroundRole:
            if item.get("imported_node_name") or item.get("has_imported"):
                return QtGui.QColor(255, 165, 0)
                
        elif role == QtCore.Qt.ToolTipRole:
            path = item.get("path", "")
            if item.get("is_sequence"):
                return f"Sequence: {path}\nFrames: {item.get('frames', '')}"
            return path
                
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal:
            if role == QtCore.Qt.DisplayRole:
                return self._headers[section]
            if role == QtCore.Qt.ToolTipRole:
                tooltips = [
                    "File or sequence name",
                    "Version number extracted from path",
                    "Frame range (for sequences)",
                    "File owner/user",
                    "Last modified date",
                    "File or sequence size"
                ]
                if 0 <= section < len(tooltips):
                    return tooltips[section]
        return None

    def flags(self, index):
        default_flags = super(FileTreeModel, self).flags(index)
        if index.isValid():
            return default_flags | QtCore.Qt.ItemIsDragEnabled
        return default_flags

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        mime_data = QtCore.QMimeData()
        urls = []
        rows = set()
        for index in indexes:
            node = index.internalPointer()
            if node not in rows:
                rows.add(node)
                path = node._data.get("path")
                if path:
                    urls.append(QtCore.QUrl.fromLocalFile(path))
        mime_data.setUrls(urls)
        return mime_data

    def update_data(self, new_data):
        self.beginResetModel()
        self.root_item = FileTreeItem(None, is_root=True)
        
        # Build tree structure from relpath
        nodes = {} # path -> FileTreeItem
        
        # Sort items by relpath length to ensure parents are created before children
        # But scanner already returns folders generally. 
        # For safety, we'll build nodes as we find them.
        
        for item in new_data:
            relpath = item.get("relpath", "")
            if not relpath:
                continue
                
            parts = relpath.split("/")
            current_parent = self.root_item
            path_accum = ""
            
            is_imported = bool(item.get("imported_node_name"))
            
            for i, part in enumerate(parts):
                path_accum = "/".join(parts[:i+1])
                
                if path_accum in nodes:
                    current_parent = nodes[path_accum]
                    if is_imported:
                        current_parent._data["has_imported"] = True
                else:
                    # If this is the last part, it's the actual item from scanner
                    if i == len(parts) - 1:
                        new_node = FileTreeItem(item, parent=current_parent)
                    else:
                        # Dummy folder node (should be replaced if found in scanner later)
                        new_node = FileTreeItem({"name": part, "is_folder": True, "has_imported": is_imported}, parent=current_parent)
                    
                    current_parent.appendChild(new_node)
                    nodes[path_accum] = new_node
                    current_parent = new_node
                    
        self.endResetModel()

class FileGroupModel(FileTreeModel):
    def update_data(self, new_data):
        self.beginResetModel()
        self.root_item = FileTreeItem(None, is_root=True)
        
        # Group items by base name (prefix + suffix from scanner)
        groups = {} # base_name -> list of items
        
        for item in new_data:
            if item.get("is_folder"):
                continue # Skip raw folders in grouped view for clarity? 
            
            # Use 'version_group' key provided by FileScanner
            key = item.get("version_group")
            if not key:
                # If no version found by scanner, use full name
                key = item.get("name", "Unknown")
            else:
                # key is currently a string representation like "(prefix, suffix)"
                # Let's make it more friendly
                import ast
                try:
                    p, s = ast.literal_eval(key)
                    key = f"{p}...{s}"
                except:
                    pass
            
            if key not in groups:
                groups[key] = []
            groups[key].append(item)
            
        # Build the tree
        for group_name, items in sorted(groups.items()):
            # Create a group header node
            # Show summary data in the header (latest version frames/size)
            latest = items[0] if items else {}
            has_imported = any(bool(it.get("imported_node_name")) for it in items)
            group_data = {
                "name": group_name,
                "version": f"({len(items)} versions)",
                "frames": latest.get("frames", ""),
                "owner": latest.get("owner", ""),
                "date": latest.get("date", ""),
                "size_str": f"Grouped {len(items)} items",
                "is_folder": True, # Expandable
                "type": "Group", # Mark as a virtual grouping folder
                "has_imported": has_imported
            }
            group_node = FileTreeItem(group_data, parent=self.root_item)
            self.root_item.appendChild(group_node)
            
            for item in items:
                # The children are the actual versions, showing their full path
                # so we can see where they are
                child_item = dict(item)
                child_item["name"] = f"[{os.path.basename(os.path.dirname(item['path']))}] {item['name']}"
                child_node = FileTreeItem(child_item, parent=group_node)
                group_node.appendChild(child_node)
                
        self.endResetModel()


class ScanWorker(QtCore.QThread):
    scan_finished = QtCore.Signal(list)
    progress_updated = QtCore.Signal(int)
    
    def __init__(self, scanner, path, parent=None):
        super(ScanWorker, self).__init__(parent)
        self.scanner = scanner
        self.path = path
        
    def _progress_callback(self, items, info):
        self.progress_updated.emit(info.get("progress", 0))

    def run(self):
        results = self.scanner.scan(self.path, callback=self._progress_callback)
        self.scan_finished.emit(results)


class PreviewLabel(QtWidgets.QLabel):
    """Custom label that supports sequence playback on mouse hover using sliced tiled filmstrips."""
    def __init__(self, parent=None):
        super(PreviewLabel, self).__init__(parent)
        self.setMouseTracking(True)
        self.playback_timer = QtCore.QTimer(self)
        self.playback_timer.timeout.connect(self.play_next_strip_frame)
        self.playback_timer.setInterval(100) # ~10 fps for preview
        
        self.item = None
        self.parent_app = None # Reference to Kadatha app
        
        self.strip_pixmap = None
        self.single_pixmap = None
        self.cols = 1
        self.current_strip_frame = 0
        self.frame_width = 0

    def set_item(self, item, app):
        self.item = item
        self.parent_app = app
        self.stop_playback()
        self.strip_pixmap = None
        self.single_pixmap = None
        self.cols = 1
        self.current_strip_frame = 0
        self.frame_width = 0

    def set_single_pixmap(self, pixmap):
        self.single_pixmap = pixmap
        if pixmap and not pixmap.isNull():
            aspect = float(pixmap.width()) / float(pixmap.height()) if pixmap.height() > 0 else 1.5
            calc_width = int(aspect * 200)
            self.setFixedSize(QtCore.QSize(calc_width, 200))
            self.setPixmap(pixmap.scaled(calc_width, 200, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation))
        else:
            self.setPixmap(QtGui.QPixmap())

    def set_strip_pixmap(self, pixmap, cols):
        self.strip_pixmap = pixmap
        self.cols = max(1, cols)
        if pixmap and not pixmap.isNull():
            self.frame_width = pixmap.width() // self.cols
        else:
            self.frame_width = 0

    def enterEvent(self, event):
        if self.strip_pixmap and not self.strip_pixmap.isNull() and self.cols > 1:
            self.start_playback()
        super(PreviewLabel, self).enterEvent(event)

    def leaveEvent(self, event):
        self.stop_playback()
        super(PreviewLabel, self).leaveEvent(event)

    def start_playback(self):
        self.current_strip_frame = 0
        self.playback_timer.start()

    def stop_playback(self):
        self.playback_timer.stop()
        if self.single_pixmap:
            self.setPixmap(self.single_pixmap.scaled(self.size(), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation))

    def play_next_strip_frame(self):
        if not self.strip_pixmap or self.frame_width <= 0:
            return
            
        self.current_strip_frame = (self.current_strip_frame + 1) % self.cols
        
        # Crop the current frame from the horizontal strip
        frame_pixmap = self.strip_pixmap.copy(self.current_strip_frame * self.frame_width, 0, self.frame_width, self.strip_pixmap.height())
        self.setPixmap(frame_pixmap.scaled(self.size(), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation))

class FFmpegPreviewWorker(QtCore.QThread):
    """Background worker for preview generation using ffmpeg in a persistent thread with dual-stage caching."""
    finished = QtCore.Signal(QtGui.QImage, str, bool, int) # image, path, is_strip, cols
    failed = QtCore.Signal(str) # path
    
    def __init__(self, parent=None):
        super(FFmpegPreviewWorker, self).__init__(parent)
        self.queue = queue.Queue()
        self.active = True
        self.lock = threading.Lock()
        self.current_process = None

    def request_preview(self, path, is_seq=False, first_frame=0, last_frame=0, seq_path=None, source_mtime=0):
        # Clear queue of stale requests
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
                
        # Terminate active ffmpeg process immediately for responsiveness
        with self.lock:
            if self.current_process:
                try:
                    self.current_process.terminate()
                except Exception:
                    pass
        
        self.queue.put((path, is_seq, first_frame, last_frame, seq_path, source_mtime))

    def stop(self):
        self.active = False
        self.queue.put(None) # Wake up queue from blocking get()
        with self.lock:
            if self.current_process:
                try:
                    self.current_process.terminate()
                except Exception:
                    pass

    def run(self):
        while self.active:
            try:
                job = self.queue.get()
                if job is None or not self.active:
                    break
                
                path, is_seq, first_frame, last_frame, seq_path, source_mtime = job
                
                norm_path = os.path.normpath(path).replace('\\', '/')
                
                # Cache checking based on original path/pattern
                cache_key_path = seq_path if seq_path else path
                single_cache, strip_cache = get_cache_paths(cache_key_path)
                
                # Check video extension
                ext = os.path.splitext(norm_path)[1].lower()
                is_video = ext in [".mov", ".mp4", ".mkv", ".avi", ".webm", ".m4v"]
                
                # ----------------- STAGE 1: Extract Single Frame (Frame 2) -----------------
                loaded_single = False
                q_single = None
                
                if is_cache_valid(single_cache, source_mtime):
                    q_single = QtGui.QImage(single_cache)
                    if q_single and not q_single.isNull():
                        loaded_single = True
                        
                if not loaded_single:
                    # Not cached or invalid: extract and save to single_cache
                    if is_video:
                        cmd = [
                            FFMPEG_PATH,
                            "-y",
                            "-i", norm_path,
                            "-vf", "select=eq(n\,1),scale=-2:200",
                            "-vframes", "1",
                            single_cache
                        ]
                    else:
                        cmd = [
                            FFMPEG_PATH,
                            "-y",
                            "-i", norm_path,
                            "-vframes", "1",
                            "-vf", "scale=-2:200",
                            single_cache
                        ]
                        
                    startupinfo = None
                    if os.name == 'nt':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        
                    with self.lock:
                        if not self.active:
                            break
                        self.current_process = subprocess.Popen(
                            cmd,
                            startupinfo=startupinfo
                        )
                        
                    self.current_process.wait()
                    with self.lock:
                        self.current_process = None
                        
                    # Fallback for video frame eq(n, 1) in case it failed
                    if is_video and not os.path.exists(single_cache):
                        cmd_fallback = [
                            FFMPEG_PATH,
                            "-y",
                            "-i", norm_path,
                            "-vframes", "1",
                            "-vf", "scale=-2:200",
                            single_cache
                        ]
                        with self.lock:
                            if not self.active:
                                break
                            self.current_process = subprocess.Popen(
                                cmd_fallback,
                                startupinfo=startupinfo
                            )
                        self.current_process.wait()
                        with self.lock:
                            self.current_process = None
                            
                    if os.path.exists(single_cache):
                        q_single = QtGui.QImage(single_cache)
                        if q_single and not q_single.isNull():
                            loaded_single = True
                            
                if loaded_single and q_single:
                    self.finished.emit(q_single, path, False, 1) # is_strip = False, cols = 1
                else:
                    self.failed.emit(path)
                    continue
                    
                # ----------------- STAGE 2: Extract Contact Strip (Filmstrip) -----------------
                if not self.active:
                    break
                    
                # Calculate cols
                cols = 0
                if is_seq:
                    num_frames = last_frame - first_frame + 1
                    cols = (num_frames + 9) // 10
                elif is_video:
                    total_frames = get_video_frame_count(norm_path)
                    cols = (total_frames + 9) // 10
                    cols = min(cols, 50) # limit to 50 columns to prevent giant frames
                    
                if cols > 0:
                    loaded_strip = False
                    q_strip = None
                    
                    if is_cache_valid(strip_cache, source_mtime):
                        q_strip = QtGui.QImage(strip_cache)
                        if q_strip and not q_strip.isNull():
                            loaded_strip = True
                            
                    if not loaded_strip:
                        startupinfo = None
                        if os.name == 'nt':
                            startupinfo = subprocess.STARTUPINFO()
                            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            
                        if is_seq and seq_path:
                            norm_seq_path = os.path.normpath(seq_path).replace('\\', '/')
                            strip_cmd = [
                                FFMPEG_PATH,
                                "-y",
                                "-start_number", str(first_frame),
                                "-i", norm_seq_path,
                                "-vf", f"select=not(mod(n\,10)),scale=-2:100,tile={cols}x1",
                                strip_cache
                            ]
                        elif is_video:
                            strip_cmd = [
                                FFMPEG_PATH,
                                "-y",
                                "-i", norm_path,
                                "-vf", f"select=not(mod(n\,10)),scale=-2:100,tile={cols}x1",
                                "-vframes", str(cols * 10),
                                strip_cache
                            ]
                        else:
                            strip_cmd = None
                            
                        if strip_cmd:
                            with self.lock:
                                if not self.active:
                                    break
                                self.current_process = subprocess.Popen(
                                    strip_cmd,
                                    startupinfo=startupinfo
                                )
                            self.current_process.wait()
                            with self.lock:
                                self.current_process = None
                                
                        if os.path.exists(strip_cache):
                            q_strip = QtGui.QImage(strip_cache)
                            if q_strip and not q_strip.isNull():
                                loaded_strip = True
                                
                    if loaded_strip and q_strip:
                        self.finished.emit(q_strip, path, True, cols) # is_strip = True, cols
            except Exception as e:
                print(f"FFmpegPreviewWorker thread exception: {e}")
                try:
                    self.failed.emit(path)
                except:
                    pass

class TypeFilterProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super(TypeFilterProxyModel, self).__init__(parent)
        self.show_files = True
        self.show_folders = True
        self.or_groups = []
        self.negative_terms = []
        self.sort_used_first = False

    def lessThan(self, left, right):
        model = self.sourceModel()
        if not model:
            return super(TypeFilterProxyModel, self).lessThan(left, right)
            
        if self.sort_used_first:
            left_item = model.data(left, QtCore.Qt.UserRole)
            right_item = model.data(right, QtCore.Qt.UserRole)
            if left_item and right_item:
                left_hl = bool(left_item.get("imported_node_name") or left_item.get("has_imported"))
                right_hl = bool(right_item.get("imported_node_name") or right_item.get("has_imported"))
                if left_hl != right_hl:
                    is_asc = (self.sortOrder() == QtCore.Qt.AscendingOrder)
                    if left_hl:
                        return is_asc
                    else:
                        return not is_asc
                        
        if left.column() == 0:
            left_data = model.data(left, QtCore.Qt.DisplayRole)
            right_data = model.data(right, QtCore.Qt.DisplayRole)
            
            if isinstance(left_data, str) and isinstance(right_data, str):
                import re
                def pad_numbers(match):
                    return f"{int(match.group(1)):010d}"
                
                try:
                    left_key = re.sub(r'(\d+)', pad_numbers, left_data.lower())
                    right_key = re.sub(r'(\d+)', pad_numbers, right_data.lower())
                    return left_key < right_key
                except:
                    pass

        return super(TypeFilterProxyModel, self).lessThan(left, right)

    def set_search_text(self, text):
        self.or_groups = [] # List of lists (AND groups)
        self.negative_terms = []
        
        if not text:
            return
            
        # 1. Parse into segments by space (OR logic)
        segments = text.split()
        for seg in segments:
            if seg.startswith("-") and len(seg) > 1:
                self.negative_terms.append(seg[1:].lower())
            elif "+" in seg:
                # AND Group
                and_terms = [t.lower() for t in seg.split("+") if t]
                if and_terms:
                    self.or_groups.append(and_terms)
            else:
                # Single term (effectively an AND group of 1)
                self.or_groups.append([seg.lower()])

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if not model:
            return False
            
        # Get the item data
        idx = model.index(source_row, 0, source_parent)
        item = model.data(idx, QtCore.Qt.UserRole)
        if not item:
            return True # Dummy items are allowed to pass to check children
            
        name = str(item.get("name", "")).lower()
        is_folder = item.get("is_folder", False)
        item_type = item.get("type", "")
        
        # 1. Type Filtering (Files / Folders)
        if is_folder and item_type == "Group":
            pass
        elif is_folder and not self.show_folders:
            return False
        elif not is_folder and not self.show_files:
            return False
            
        # 2. Advanced Boolean Text Filtering
        # Logic: (NOT negative_terms) AND (OR of or_groups)
        # where each or_group is (AND of its terms)
        
        # Check Exclusions (Global NOT)
        for neg in self.negative_terms:
            if neg in name:
                return False
        
        # If no positive terms, we pass the text filter
        if not self.or_groups:
            return True
            
        # Check OR Groups
        for and_group in self.or_groups:
            # Check if this group matches (ALL terms in group must match)
            group_matches = True
            for term in and_group:
                if term not in name:
                    group_matches = False
                    break
            
            # If any group matches, the whole OR condition is met
            if group_matches:
                return True
                        
        return False


class KadathaConfigDialog(QtWidgets.QDialog):
    def __init__(self, current_config, parent=None):
        super(KadathaConfigDialog, self).__init__(parent)
        self.setWindowTitle("Kadatha - Configuration")
        self.resize(500, 600)
        self.config = dict(current_config)
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header Section
        header_frame = QtWidgets.QFrame()
        header_frame.setStyleSheet("background-color: #2a2a2a; border-radius: 6px; padding: 12px;")
        header_layout = QtWidgets.QVBoxLayout(header_frame)
        
        title = QtWidgets.QLabel("KADATHA")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #00A3FF; letter-spacing: 1.5px;")
        header_layout.addWidget(title)
        
        subtitle = QtWidgets.QLabel("File Browser for Nuke")
        subtitle.setStyleSheet("font-size: 13px; color: #999; font-style: italic;")
        header_layout.addWidget(subtitle)
        
        info = QtWidgets.QLabel('Developed for nuke by <a href="https://github.com/pbhat99" style="color: #00A3FF; text-decoration: none;">Prasannakumar T Bhat</a> | Version 1.1.0 | Licence: Apache 2.0')
        info.setOpenExternalLinks(True)
        info.setStyleSheet("font-size: 11px; color: #777; margin-top: 8px;")
        header_layout.addWidget(info)
        
        credits = QtWidgets.QLabel('Thanks:<a href="https://github.com/richardssam" style="color: #666; text-decoration: none;">Sam Richards</a> for original code and concept (FileSystem browser for xSTUDIO)')
        credits.setOpenExternalLinks(True)
        credits.setStyleSheet("font-size: 10px; color: #555; margin-top: 2px;")
        header_layout.addWidget(credits)
        
        layout.addWidget(header_frame)
        
        # Form Section
        form = QtWidgets.QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        
        self.ext_edit = QtWidgets.QPlainTextEdit(", ".join(self.config.get("extensions", [])))
        self.ext_edit.setMaximumHeight(80)
        self.ext_edit.setToolTip("Comma-separated list of file extensions to include in scan")
        form.addRow("Extensions:", self.ext_edit)
        
        self.ignore_edit = QtWidgets.QPlainTextEdit(", ".join(self.config.get("ignore_dirs", [])))
        self.ignore_edit.setMaximumHeight(80)
        self.ignore_edit.setToolTip("Comma-separated list of directory and file names to ignore (e.g. .git, thumbs.db)")
        form.addRow("Ignore List:", self.ignore_edit)
        
        self.non_seq_edit = QtWidgets.QPlainTextEdit(", ".join(self.config.get("non_sequence_extensions", [])))
        self.non_seq_edit.setMaximumHeight(60)
        self.non_seq_edit.setToolTip("Extensions that should never be treated as sequences (e.g. mov, mp4)")
        form.addRow("Single Files:", self.non_seq_edit)
        
        self.depth_spin = QtWidgets.QSpinBox()
        self.depth_spin.setRange(0, 25)
        self.depth_spin.setValue(self.config.get("max_depth", 0))
        form.addRow("Default Depth:", self.depth_spin)
        
        self.threads_spin = QtWidgets.QSpinBox()
        self.threads_spin.setRange(1, 16)
        self.threads_spin.setValue(self.config.get("thread_count", 4))
        form.addRow("Thread Count:", self.threads_spin)
        
        self.history_spin = QtWidgets.QSpinBox()
        self.history_spin.setRange(1, 100)
        self.history_spin.setValue(self.config.get("history_limit", 15))
        form.addRow("Address Bar History:", self.history_spin)
        
        self.fav_limit_spin = QtWidgets.QSpinBox()
        self.fav_limit_spin.setRange(1, 100)
        self.fav_limit_spin.setValue(self.config.get("favorites_limit", 20))
        form.addRow("Address Bar Favorites:", self.fav_limit_spin)
        
        self.regex_edit = QtWidgets.QLineEdit(str(self.config.get("version_regex", "")))
        form.addRow("Version Regex:", self.regex_edit)
        
        # FFmpeg Directory Browse Option
        ffmpeg_widget = QtWidgets.QWidget()
        ffmpeg_hl = QtWidgets.QHBoxLayout(ffmpeg_widget)
        ffmpeg_hl.setContentsMargins(0, 0, 0, 0)
        ffmpeg_hl.setSpacing(5)
        
        self.ffmpeg_dir_edit = QtWidgets.QLineEdit(str(self.config.get("ffmpeg_dir", "")))
        self.ffmpeg_dir_edit.setPlaceholderText("Path to FFmpeg directory (e.g. C:/ffmpeg/bin)")
        self.ffmpeg_dir_edit.setToolTip("Custom path to FFmpeg binary folder (overrides default search)")
        
        self.ffmpeg_browse_btn = QtWidgets.QPushButton("Browse...")
        self.ffmpeg_browse_btn.clicked.connect(self.browse_ffmpeg_dir)
        self.ffmpeg_browse_btn.setStyleSheet("padding: 4px 10px; background-color: #2b2b2b; border: 1px solid #00A3FF; border-radius: 4px;")
        
        ffmpeg_hl.addWidget(self.ffmpeg_dir_edit)
        ffmpeg_hl.addWidget(self.ffmpeg_browse_btn)
        form.addRow("FFmpeg Directory:", ffmpeg_widget)
        
        self.enable_edit_cb = QtWidgets.QCheckBox("Enable Delete and Rename in Context Menu")
        self.enable_edit_cb.setChecked(self.config.get("enable_delete_rename", False))
        self.enable_edit_cb.setToolTip("Safety: If enabled, you can rename and delete files/folders from the right-click menu.")
        form.addRow("File Mutations:", self.enable_edit_cb)
        
        layout.addLayout(form)
        
        # Buttons
        self.btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        
        # Add Reset button
        self.reset_btn = self.btn_box.addButton("Factory Reset", QtWidgets.QDialogButtonBox.ResetRole)
        self.reset_btn.setStyleSheet("color: #ff6666; font-weight: bold;")
        self.reset_btn.setToolTip("Deletes all configurations and preferences for a fresh start. Irreversible!")
        self.reset_btn.clicked.connect(self.on_reset_clicked)
        
        layout.addWidget(self.btn_box)

    def browse_ffmpeg_dir(self):
        curr_dir = self.ffmpeg_dir_edit.text().strip()
        if not curr_dir or not os.path.exists(curr_dir):
            curr_dir = os.path.expanduser("~")
        
        selected_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select FFmpeg Folder", curr_dir, 
            QtWidgets.QFileDialog.ShowDirsOnly | QtWidgets.QFileDialog.DontResolveSymlinks
        )
        if selected_dir:
            self.ffmpeg_dir_edit.setText(selected_dir.replace('\\', '/'))

    def on_reset_clicked(self):
        msg = "Are you sure you want to perform a factory reset?\n\nThis will permanently delete:\n- Configuration (JSON)\n- Preferences (Favorites, History, Search History, Layouts)\n\nThe tool will immediately revert to factory defaults."
        res = QtWidgets.QMessageBox.warning(self, "Factory Reset Confirmation", msg, 
                                           QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if res == QtWidgets.QMessageBox.Yes:
            # Custom code for Reset action
            self.done(100)

    def get_config(self):
        def parse_list(text):
            return [t.strip() for t in text.replace('\n', ',').split(',') if t.strip()]
            
        new_config = {
            "extensions": parse_list(self.ext_edit.toPlainText()),
            "ignore_dirs": parse_list(self.ignore_edit.toPlainText()),
            "non_sequence_extensions": parse_list(self.non_seq_edit.toPlainText()),
            "max_depth": self.depth_spin.value(),
            "thread_count": self.threads_spin.value(),
            "history_limit": self.history_spin.value(),
            "favorites_limit": self.fav_limit_spin.value(),
            "version_regex": self.regex_edit.text(),
            "enable_delete_rename": self.enable_edit_cb.isChecked(),
            "ffmpeg_dir": self.ffmpeg_dir_edit.text().strip()
        }
        return new_config


class RenameDialog(QtWidgets.QDialog):
    def __init__(self, initial_text, parent=None):
        super(RenameDialog, self).__init__(parent)
        self.setWindowTitle("Kadatha - Rename Item")
        # 3x more wider (standard is ~200-250, so 600-750 is good)
        self.setMinimumWidth(750)
        self.setup_ui(initial_text)

    def setup_ui(self, initial_text):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        label = QtWidgets.QLabel("Enter New Name / Prefix:")
        # label.setStyleSheet("font-weight: bold; color: #ccc;")
        layout.addWidget(label)

        self.line_edit = QtWidgets.QLineEdit(initial_text)
        #self.line_edit.setMinimumHeight(35)
        # self.line_edit.setStyleSheet("""
        #     QLineEdit {
        #         background-color: #1a1a1a;
        #         border: 1px solid #333;
        #         border-radius: 4px;
        #         padding: 5px;
        #         font-size: 14px;
        #         color: #fff;
        #     }
        #     QLineEdit:focus {
        #         border-color: #00A3FF;
        #     }
        # """)
        # #self.line_edit.selectAll()
        layout.addWidget(self.line_edit)

        tip = QtWidgets.QLabel("Tip: For sequences, you can just enter the new prefix. To change padding, include #### or %04d tokens.")
        # tip.setStyleSheet("font-size: 10px; color: #777; font-style: italic;")
        #layout.addWidget(tip)

        self.btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)

    def get_text(self):
        return self.line_edit.text()


class Kadatha(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(Kadatha, self).__init__(parent)
        
        # Scanner initialization
        self.config = self.load_config()
        resolve_ffmpeg_paths(self.config)
        self.scanner = FileScanner(self.config)
        self.scan_worker = None
        self.cached_results = []
        self.ffmpeg_available = check_ffmpeg_available()
        self.ffmpeg_worker = None
        self.load_user_settings()
        
        # Determine current path from settings or Home
        if self.saved_last_path and os.path.exists(self.saved_last_path):
            self.current_path = self.saved_last_path
        else:
            self.current_path = os.path.expanduser("~")
        
        print("Initializing Kadatha Panel...")
        self.setup_ui()
        
    def get_settings_obj(self):
        nuke_dir = os.path.expanduser("~/.nuke")
        if not os.path.exists(nuke_dir):
            try:
                os.makedirs(nuke_dir)
            except:
                pass
        settings_path = os.path.join(nuke_dir, "Kadatha_Settings.ini")
        return QtCore.QSettings(settings_path, QtCore.QSettings.IniFormat)

    def load_user_settings(self):
        settings = self.get_settings_obj()
        
        # Load favorites
        favs = settings.value("favorites", [])
        if isinstance(favs, str):
            self.favorites = [favs] if favs else []
        else:
            self.favorites = list(favs) if favs else []
            
        # Load layout - store in temporary dict for setup_ui to use
        self.saved_splitter_sizes = settings.value("splitter_sizes")
        self.saved_left_splitter_sizes = settings.value("left_splitter_sizes")
        self.saved_sort_column = settings.value("sort_column")
        self.saved_sort_order = settings.value("sort_order")
        self.saved_list_widths = settings.value("list_widths")
        self.saved_tree_widths = settings.value("tree_widths")
        self.saved_group_widths = settings.value("group_widths")
        self.saved_view_index = settings.value("view_index", 0)
        self.saved_last_path = settings.value("last_path")
        self.saved_preview_visible = settings.value("preview_visible", "true") == "true"
        self.saved_sidebar_visible = settings.value("sidebar_visible", "true") == "true"
        self.saved_bundle_sequences = settings.value("bundle_sequences", "true") == "true"
        self.saved_sort_used_first = settings.value("sort_used_first", "true") == "true"
        
        history = settings.value("history", [])
        if isinstance(history, str):
            self.history = [history] if history else []
        else:
            self.history = list(history) if history else []
        self.history = self.history[:self.config.get("history_limit", 15)] # Limit history
        
        search_history = settings.value("search_history", [])
        if isinstance(search_history, str):
            self.search_history = [search_history] if search_history else []
        else:
            self.search_history = list(search_history) if search_history else []
        self.search_history = self.search_history[:15] # Limit search history to 15

    def save_user_settings(self):
        # Prevent saving during initialization if widgets aren't ready
        if not hasattr(self, 'splitter') or not hasattr(self, 'view_stack'):
            return
            
        settings = self.get_settings_obj()
        settings.setValue("favorites", self.favorites)
        settings.setValue("splitter_sizes", self.splitter.sizes())
        if hasattr(self, 'left_splitter'):
            settings.setValue("left_splitter_sizes", self.left_splitter.sizes())
        settings.setValue("view_index", self.view_stack.currentIndex())
        settings.setValue("last_path", self.current_path)
        settings.setValue("history", self.history)
        settings.setValue("search_history", self.search_history)
        settings.setValue("preview_visible", self.preview_btn.isChecked())
        settings.setValue("sidebar_visible", self.sidebar_btn.isChecked())
        settings.setValue("bundle_sequences", self.filter_sequences_cb.isChecked())
        settings.setValue("sort_used_first", self.sort_used_first_cb.isChecked())
        
        view = self.view_stack.currentWidget()
        header = view.header() if hasattr(view, 'header') else view.horizontalHeader()
        settings.setValue("sort_column", header.sortIndicatorSection())
        # Use .value to avoid TypeError in PySide6/Nuke16
        sort_order = header.sortIndicatorOrder()
        settings.setValue("sort_order", int(sort_order.value if hasattr(sort_order, 'value') else sort_order))
        
        col_widths = []
        for i in range(header.count()):
            col_widths.append(header.sectionSize(i))
            
        if self.view_stack.currentIndex() == 0:
            settings.setValue("list_widths", col_widths)
        elif self.view_stack.currentIndex() == 1:
            settings.setValue("tree_widths", col_widths)
        else:
            settings.setValue("group_widths", col_widths)
        
        settings.sync()
            
    def hideEvent(self, event):
        self.save_user_settings()
        if hasattr(self, 'ffmpeg_worker') and self.ffmpeg_worker and self.ffmpeg_worker.isRunning():
            self.ffmpeg_worker.stop()
            self.ffmpeg_worker.wait()
        super(Kadatha, self).hideEvent(event)
        
    def closeEvent(self, event):
        self.save_user_settings()
        if hasattr(self, 'ffmpeg_worker') and self.ffmpeg_worker and self.ffmpeg_worker.isRunning():
            self.ffmpeg_worker.stop()
            self.ffmpeg_worker.wait()
        super(Kadatha, self).closeEvent(event)
            
    def rebuild_favorites_ui(self):
        while self.favorites_bar.count():
            item = self.favorites_bar.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for fav_path in self.favorites:
            name = os.path.basename(fav_path)
            if not name:
                name = fav_path
            btn = QtWidgets.QPushButton(name)
            btn.setToolTip(fav_path)
            # Use default argument p=fav_path so loop scope isn't leaked into lambda
            btn.clicked.connect(lambda checked=False, p=fav_path: self.set_path(p))
            btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, b=btn, p=fav_path: self.remove_favorite_menu(pos, b, p))
            self.favorites_bar.addWidget(btn)
            
        self.favorites_bar.addStretch(1)
        if hasattr(self, 'fav_container'):
            self.fav_container.update()

    def remove_favorite_menu(self, pos, btn, path):
        menu = QtWidgets.QMenu(self)
        remove_action = menu.addAction("Remove from Favorites")
        action = menu.exec_(btn.mapToGlobal(pos))
        if action == remove_action:
            if path in self.favorites:
                self.favorites.remove(path)
                self.save_user_settings()
                self.rebuild_favorites_ui()

    def tree_context_menu(self, pos):
        index = self.tree_view.indexAt(pos)
        if not index.isValid():
            return
            
        # Map proxy index back to source model
        source_index = self.sidebar_proxy.mapToSource(index)
        path = self.tree_model.filePath(source_index)
        if not os.path.isdir(path):
            path = os.path.dirname(path)
            
        menu = QtWidgets.QMenu(self)
        if path in self.favorites:
            fav_action = menu.addAction(STAR_ICON, "Remove from Favorites")
        else:
            fav_action = menu.addAction(STAR_ICON, "Add to Favorites")
            
        explorer_action = menu.addAction("Open in Explorer")
        copy_path_action = menu.addAction("Copy Path")
            
        action = menu.exec_(self.tree_view.viewport().mapToGlobal(pos))
        if action == fav_action:
            if path in self.favorites:
                self.favorites.remove(path)
            else:
                self.favorites.append(path)
            self.save_user_settings()
            self.rebuild_favorites_ui()
            
        elif action == explorer_action:
            self.open_in_explorer(path)
        elif action == copy_path_action:
            self.copy_to_clipboard(path)

    def get_config_path(self):
        return os.path.expanduser("~/.nuke/Kadatha_config.json")

    def load_config(self):
        config_path = self.get_config_path()
        # Fallback for migration if new config doesn't exist yet
        old_path = os.path.join(os.path.dirname(__file__), "config.json")
        
        default_config = {
            "extensions": [".mov", ".mp4", ".mkv", ".exr", ".jpg", ".jpeg", ".png", 
                           ".dpx", ".tiff", ".tif", ".wav", ".mp3", ".abc", ".fbx", ".obj"],
            "ignore_dirs": [".git", ".quarantine", "eryx_unreal_plugin", ".DS_Store", "cache","rendergallery.db","rendergallery"],
            "max_depth": 0,
            "thread_count": 4,
            "version_regex": "[._]v(\\d+)|v(\\d+)",
            "history_limit": 15,
            "favorites_limit": 20,
            "bundle_sequences": True,
            "enable_delete_rename": False,
            "non_sequence_extensions": [".mov", ".mp4", ".abc", ".fbx", ".obj", ".wav", ".mp3"],
            "ffmpeg_dir": ""
        }
        
        # Try new path first, then old path
        found_path = None
        if os.path.exists(config_path):
            found_path = config_path
        elif os.path.exists(old_path):
            found_path = old_path
            
        if found_path:
            try:
                with open(found_path, 'r') as f:
                    loaded_config = json.load(f)
                    for key, value in loaded_config.items():
                        default_config[key] = value
            except Exception as e:
                print(f"Error loading config from {found_path}: {e}")
        
        return default_config
        
    def setup_ui(self):
        self.setWindowTitle("Kadatha")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(4)
        
        # --- Top Bar ---
        top_bar = QtWidgets.QHBoxLayout()

        self.up_btn = QtWidgets.QPushButton("Up")
        self.up_btn.setToolTip("Go up one directory")
        self.up_btn.clicked.connect(self.go_up)
        top_bar.addWidget(self.up_btn)
        
        self.path_edit = QtWidgets.QComboBox()
        self.path_edit.setEditable(True)
        self.path_edit.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.path_edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.path_edit.addItems(self.history)
        self.path_edit.setEditText(self.current_path)
        self.path_edit.setToolTip("Current directory path. Press Enter to navigate or select from history/favorites.")
        
        self.path_edit.lineEdit().returnPressed.connect(self.path_changed)
        self.path_edit.activated.connect(self.on_path_selected)
        top_bar.addWidget(self.path_edit)

        depth_label = QtWidgets.QLabel("Depth:")
        depth_label.setToolTip("Search depth for subdirectories (0 = current folder only)")
        top_bar.addWidget(depth_label)
        self.depth_spin = QtWidgets.QSpinBox()
        self.depth_spin.setRange(0, 25)
        self.depth_spin.setValue(self.scanner.max_depth)
        self.depth_spin.setToolTip("Search depth for subdirectories (0 = current folder only)")
        self.depth_spin.valueChanged.connect(self.depth_changed)
        top_bar.addWidget(self.depth_spin)
        
        self.locate_btn = QtWidgets.QPushButton("Locate")
        self.locate_btn.setToolTip("Locate folder of selected node or script")
        self.locate_btn.clicked.connect(self.locate_node_path)
        top_bar.addWidget(self.locate_btn)
        
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.setToolTip("Force scan current directory")
        self.refresh_btn.clicked.connect(self.refresh)
        top_bar.addWidget(self.refresh_btn)
        
        layout.addLayout(top_bar)
        
        # --- Filter Bar ---
        filter_bar = QtWidgets.QHBoxLayout()
        
        self.sidebar_btn = QtWidgets.QPushButton("Sidebar")
        self.sidebar_btn.setCheckable(True)
        self.sidebar_btn.setChecked(True)
        self.sidebar_btn.setToolTip("Toggle Directory Tree")
        self.sidebar_btn.clicked.connect(self.toggle_sidebar)
        filter_bar.addWidget(self.sidebar_btn)
        
        self.preview_btn = QtWidgets.QPushButton("Preview")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setChecked(True)
        self.preview_btn.setToolTip("Toggle File Preview Panel")
        self.preview_btn.clicked.connect(self.toggle_preview)
        filter_bar.addWidget(self.preview_btn)
        
        search_label = QtWidgets.QLabel("Search:")
        search_label.setToolTip("Filter files by name. Support exclusions (-) and inclusions (+)")
        filter_bar.addWidget(search_label)
        self.search_edit = QtWidgets.QComboBox()
        self.search_edit.setEditable(True)
        self.search_edit.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.search_edit.lineEdit().setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("Filter String...")
        self.search_edit.setToolTip("Search files. Use '-' to exclude (e.g. -temp), '+' for AND logic (e.g. plate+low).")
        self.search_edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.search_edit.addItems(self.search_history)
        self.search_edit.setEditText("")
        
        self.search_edit.lineEdit().textChanged.connect(self.update_filters)
        self.search_edit.lineEdit().returnPressed.connect(self.store_search_history)
        self.search_edit.activated.connect(self.update_filters)
        filter_bar.addWidget(self.search_edit, 1) # stretch parameter to fill available space
        
        self.filter_folders_cb = QtWidgets.QCheckBox("Folders")
        self.filter_folders_cb.setChecked(True)
        self.filter_folders_cb.setToolTip("Toggle visibility of folders in the result list")
        self.filter_folders_cb.stateChanged.connect(self.update_filters)
        filter_bar.addWidget(self.filter_folders_cb)

        self.filter_files_cb = QtWidgets.QCheckBox("Files")
        self.filter_files_cb.setChecked(True)
        self.filter_files_cb.setToolTip("Toggle visibility of files in the result list")
        self.filter_files_cb.stateChanged.connect(self.update_filters)
        filter_bar.addWidget(self.filter_files_cb)

        self.filter_sequences_cb = QtWidgets.QCheckBox("Sequence")
        self.filter_sequences_cb.setChecked(self.saved_bundle_sequences if hasattr(self, 'saved_bundle_sequences') else self.config.get("bundle_sequences", True))
        self.filter_sequences_cb.setToolTip("Bundle file sequences into a single entry")
        self.filter_sequences_cb.stateChanged.connect(self.sequence_toggle_changed)
        filter_bar.addWidget(self.filter_sequences_cb)
        
        self.sort_used_first_cb = QtWidgets.QCheckBox("Used First")
        self.sort_used_first_cb.setChecked(self.saved_sort_used_first if hasattr(self, 'saved_sort_used_first') else True)
        self.sort_used_first_cb.setToolTip("Pin highlighted (used) items to the top of the list")
        self.sort_used_first_cb.stateChanged.connect(self.update_filters)
        filter_bar.addWidget(self.sort_used_first_cb)
        
        # Initialize scanner's bundle_sequences state
        self.scanner.bundle_sequences = self.filter_sequences_cb.isChecked()
        
        self.config_btn = QtWidgets.QPushButton("Config")
        #self.config_btn.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        self.config_btn.setToolTip("Open browser configuration and settings")
        self.config_btn.clicked.connect(self.open_config)
        filter_bar.addWidget(self.config_btn)
        
        layout.addLayout(filter_bar)
        
        # --- Favorites Area ---
        self.fav_container = QtWidgets.QWidget()
        self.favorites_bar = QtWidgets.QHBoxLayout(self.fav_container)
        self.favorites_bar.setContentsMargins(4, 2, 4, 2)
        self.favorites_bar.setSpacing(4)
        self.rebuild_favorites_ui()
        layout.addWidget(self.fav_container)
        
        # --- Splitter ---
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        
        # Left: Directory Tree & Preview
        self.left_panel = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(4)
        
        self.tree_model = QtWidgets.QFileSystemModel()
        self.tree_model.setFilter(QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllDirs)
        self.tree_model.setRootPath("")
        
        self.sidebar_proxy = QtCore.QSortFilterProxyModel(self)
        self.sidebar_proxy.setSourceModel(self.tree_model)
        self.sidebar_proxy.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.sidebar_proxy.setDynamicSortFilter(True)
        
        self.tree_view = QtWidgets.QTreeView()
        self.tree_view.setModel(self.sidebar_proxy)
        self.tree_view.setSortingEnabled(True)
        self.tree_view.sortByColumn(0, QtCore.Qt.AscendingOrder)
        self.tree_view.header().hide()
        self.tree_view.setIconSize(QtCore.QSize(0, 0)) #sidebar icons
        self.tree_view.setToolTip("Browse local directory structure")
        # Hide all columns except the name column
        for i in range(1, self.tree_model.columnCount()):
            self.tree_view.hideColumn(i)
        self.tree_view.clicked.connect(self.tree_clicked)
        self.tree_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.tree_context_menu)
        
        # --- Preview Window ---
        self.preview_container = QtWidgets.QFrame()
        self.preview_container.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.preview_container.setStyleSheet("background-color: #222; border-radius: 4px; border: 1px solid #333;")
        self.preview_layout = QtWidgets.QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(6, 6, 6, 6)
        self.preview_layout.setSpacing(3)
        
        preview_header = QtWidgets.QLabel("") # Removed header text
        preview_header.setFixedSize(QtCore.QSize(0, 0)) # Effectively hide
        
        self.preview_img = PreviewLabel()
        self.preview_img.setFixedHeight(200)
        self.preview_img.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_img.setStyleSheet("background-color: #111; border: 1px solid #222;")
        self.preview_img.setToolTip("Hover to play sequence (if single selection)")
        self.preview_layout.addWidget(self.preview_img, alignment=QtCore.Qt.AlignCenter)
        
        self.preview_info = QtWidgets.QLabel("Select a file to see details")
        self.preview_info.setStyleSheet("color: #aaa; font-size: 9px; line-height: 12px;")
        self.preview_info.setWordWrap(True)
        self.preview_layout.addWidget(self.preview_info)
        
        # Vertical Splitter to allow vertical resizing within left sidebar
        self.left_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.left_splitter.setHandleWidth(4)
        self.left_splitter.setStyleSheet("QSplitter::handle { background-color: #333; }")
        self.left_splitter.addWidget(self.tree_view)
        self.left_splitter.addWidget(self.preview_container)
        self.left_splitter.setStretchFactor(0, 2) # tree_view
        self.left_splitter.setStretchFactor(1, 1) # preview_container
        
        self.left_splitter.splitterMoved.connect(lambda x, y: self.save_user_settings())
        
        self.left_layout.addWidget(self.left_splitter)
        self.splitter.addWidget(self.left_panel)
        
        # --- Right Panel (Stacked) ---
        self.view_stack = QtWidgets.QStackedWidget()
        
        # 1. List View (Flat)
        self.list_model = FileTableModel()
        self.list_proxy = TypeFilterProxyModel()
        self.list_proxy.setSourceModel(self.list_model)
        self.list_proxy.setFilterKeyColumn(0)
        self.list_proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        
        self.list_view = QtWidgets.QTableView()
        self.list_view.setModel(self.list_proxy)
        self.list_view.setToolTip("Flat list of files and folders in current directory")
        self.list_view.setSortingEnabled(True)
        self.list_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.list_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list_view.verticalHeader().hide()
        self.list_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.list_view.setDragEnabled(True)
        self.list_view.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.list_view.doubleClicked.connect(self.table_double_clicked)
        self.list_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self.show_context_menu)
        self.list_view.horizontalHeader().setStretchLastSection(True)
        self.view_stack.addWidget(self.list_view)
        
        # 2. Tree View (Hierarchical)
        self.tree_main_model = FileTreeModel()
        self.tree_proxy = TypeFilterProxyModel()
        self.tree_proxy.setSourceModel(self.tree_main_model)
        self.tree_proxy.setFilterKeyColumn(0)
        self.tree_proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.tree_proxy.setRecursiveFilteringEnabled(True)
        
        self.tree_view_main = QtWidgets.QTreeView()
        self.tree_view_main.setModel(self.tree_proxy)
        self.tree_view_main.setToolTip("Recursive tree view showing files in subdirectories")
        self.tree_view_main.setSortingEnabled(True)
        self.tree_view_main.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.tree_view_main.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree_view_main.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tree_view_main.setDragEnabled(True)
        self.tree_view_main.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.tree_view_main.doubleClicked.connect(self.table_double_clicked)
        self.tree_view_main.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree_view_main.customContextMenuRequested.connect(self.show_context_menu)
        self.tree_view_main.header().setStretchLastSection(True)
        self.view_stack.addWidget(self.tree_view_main)
        
        # 3. Group View (Aggregated)
        self.group_model = FileGroupModel()
        self.group_proxy = TypeFilterProxyModel()
        self.group_proxy.setSourceModel(self.group_model)
        self.group_proxy.setFilterKeyColumn(0)
        self.group_proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.group_proxy.setRecursiveFilteringEnabled(True)
        
        self.group_view = QtWidgets.QTreeView()
        self.group_view.setModel(self.group_proxy)
        self.group_view.setToolTip("Aggregated view grouping all versions of the same file")
        self.group_view.setSortingEnabled(True)
        self.group_view.header().setStretchLastSection(True)
        self.group_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.group_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.group_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.group_view.setDragEnabled(True)
        self.group_view.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.group_view.doubleClicked.connect(self.table_double_clicked)
        self.group_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.group_view.customContextMenuRequested.connect(self.show_context_menu)
        self.view_stack.addWidget(self.group_view)
        
        # Selection signals for preview
        for view in [self.list_view, self.tree_view_main, self.group_view]:
            view.selectionModel().selectionChanged.connect(self.selection_changed)
        
        self.splitter.addWidget(self.view_stack)
        
        # Connect layout persistence for all views
        for view in [self.list_view, self.tree_view_main, self.group_view]:
            h = view.header() if hasattr(view, 'header') else view.horizontalHeader()
            h.sectionResized.connect(lambda: self.save_user_settings())
            h.sortIndicatorChanged.connect(lambda: self.save_user_settings())
            
        self.splitter.splitterMoved.connect(lambda x, y: self.save_user_settings())
        self.sidebar_btn.clicked.connect(lambda: self.save_user_settings())
        
        # Setup Initial State from Settings
        try:
            v_idx = int(self.saved_view_index) if self.saved_view_index is not None else 0
            self.view_stack.setCurrentIndex(v_idx)
            
            saved_sizes = self.saved_splitter_sizes
            if saved_sizes:
                self.splitter.setSizes([int(s) for s in saved_sizes])
            else:
                self.splitter.setSizes([250, 600])
                
            saved_left_sizes = self.saved_left_splitter_sizes
            if saved_left_sizes:
                self.left_splitter.setSizes([int(s) for s in saved_left_sizes])
            else:
                self.left_splitter.setSizes([400, 300])
                
            self.preview_btn.setChecked(bool(self.saved_preview_visible))
            self.preview_container.setVisible(bool(self.saved_preview_visible))
            self.sidebar_btn.setChecked(bool(self.saved_sidebar_visible))
            self.tree_view.setVisible(bool(self.saved_sidebar_visible))
        except:
            self.splitter.setSizes([250, 600])

        self.splitter.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        layout.addWidget(self.splitter, 1)

        # Restore header settings to both views
        saved_list_widths = self.saved_list_widths
        if saved_list_widths:
            try:
                for i, width in enumerate(saved_list_widths):
                    if i < self.list_view.horizontalHeader().count():
                        self.list_view.horizontalHeader().resizeSection(i, int(width))
            except: pass
            
        saved_tree_widths = self.saved_tree_widths
        if saved_tree_widths:
            try:
                for i, width in enumerate(saved_tree_widths):
                    if i < self.tree_view_main.header().count():
                        self.tree_view_main.header().resizeSection(i, int(width))
            except: pass
            
        saved_group_widths = self.saved_group_widths
        if saved_group_widths:
            try:
                for i, width in enumerate(saved_group_widths):
                    if i < self.group_view.header().count():
                        self.group_view.header().resizeSection(i, int(width))
            except: pass
                    
        try:
            sort_col = int(self.saved_sort_column) if self.saved_sort_column is not None else 0
            sort_order = int(self.saved_sort_order) if self.saved_sort_order is not None else 0
            view = self.view_stack.currentWidget()
            view.sortByColumn(sort_col, QtCore.Qt.SortOrder(sort_order))
        except: pass
        
        # --- Bottom Area ---
        bottom_area = QtWidgets.QHBoxLayout()
        
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("color: #888; font-size: 10px; padding: 2px 4px;")
        self.status_label.setToolTip("Current operation status and item count")
        bottom_area.addWidget(self.status_label, 1)
        
        # List/Tree Toggle
        self.view_btn_grp = QtWidgets.QButtonGroup(self)
        self.view_btn_grp.setExclusive(True)
        
        view_options = [
            ("List", QtWidgets.QStyle.SP_FileDialogDetailedView), 
            ("Tree", QtWidgets.QStyle.SP_FileDialogContentsView),
            ("Group", QtWidgets.QStyle.SP_FileDialogListView)
        ]
        
        for i, (name, icon) in enumerate(view_options):
            btn = QtWidgets.QPushButton(name)
            btn.setCheckable(True)
            btn.setIcon(QtWidgets.QApplication.style().standardIcon(icon))
            btn.setFixedHeight(20)
            btn.setFixedWidth(60)
            btn.setStyleSheet("font-size: 10px;")
            
            tooltips = {
                "List": "Flat list view of the current directory",
                "Tree": "Hierarchical tree view of all scanned folders",
                "Group": "Version-aggregated view grouping sequences together"
            }
            btn.setToolTip(tooltips.get(name, f"Switch to {name} view"))
            
            if i == v_idx:
                btn.setChecked(True)
            
            # Map index using default arg
            btn.clicked.connect(lambda checked=False, idx=i: self.switch_view_mode(idx))
            self.view_btn_grp.addButton(btn)
            bottom_area.addWidget(btn)
            
        layout.addLayout(bottom_area)
        
        # Progress Bar at the very bottom
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setToolTip("Scan or Load progress indicator")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: rgba(0, 0, 0, 0);
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078d4, stop:1 #00A3FF);
            }
        """)
        self.progress_bar.hide()
        
        # Remove layout spacing for the last item to make it sit at the edge
        layout.setSpacing(0)
        layout.addWidget(self.progress_bar)
        
        # Initialize
        self.set_path(self.current_path)
        self.manage_ffmpeg_worker_state()
        
    def open_config(self):
        dialog = KadathaConfigDialog(self.config, self)
        res = dialog.exec_()
        
        if res == QtWidgets.QDialog.Accepted:
            new_config = dialog.get_config()
            self.config = new_config
            resolve_ffmpeg_paths(self.config)
            self.ffmpeg_available = check_ffmpeg_available()
            self.manage_ffmpeg_worker_state()
            self.scanner = FileScanner(self.config) # Update scanner with new config
            
            # Save to file in .nuke
            config_path = self.get_config_path()
            nuke_dir = os.path.dirname(config_path)
            if not os.path.exists(nuke_dir):
                try:
                    os.makedirs(nuke_dir)
                except: pass
                
            try:
                with open(config_path, 'w') as f:
                    json.dump(new_config, f, indent=4)
                print(f"Config successfully saved to {config_path}")
                self.refresh() # Refresh view with new filters/config
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Save Error", f"Could not save {os.path.basename(config_path)}:\n{e}")
        
        elif res == 100: # Reset Code
            self.perform_factory_reset()

    def perform_factory_reset(self):
        # 1. Gather all file paths
        nuke_dir = os.path.expanduser("~/.nuke")
        config_path = self.get_config_path()
        settings_path = os.path.join(nuke_dir, "filebrowser.ini")
        
        # 2. Delete the actual files
        for p in [config_path, settings_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                    print(f"Deleted: {p}")
                except Exception as e:
                    print(f"Error removing {p}: {e}")
        
        # 3. Wipe internal state
        self.favorites = []
        self.history = []
        self.search_history = []
        self.current_path = os.path.expanduser("~")
        self.config = self.load_config() # Reload default hardcoded config
        resolve_ffmpeg_paths(self.config)
        self.ffmpeg_available = check_ffmpeg_available()
        self.manage_ffmpeg_worker_state()
        self.scanner = FileScanner(self.config)
        
        # 4. Update UI to match empty state
        self.rebuild_favorites_ui()
        self.path_edit.clear()
        self.path_edit.setEditText(self.current_path)
        
        # Reset layout if possible (optional but good for 'fresh start')
        self.splitter.setSizes([250, 600])
        self.view_stack.setCurrentIndex(0)
        
        # Trigger scan
        self.refresh()
        
        QtWidgets.QMessageBox.information(self, "Reset Success", "Kadatha has been reset to factory defaults.")
        
    def go_up(self):
        parent_dir = os.path.dirname(self.current_path)
        if parent_dir and parent_dir != self.current_path:
            self.set_path(parent_dir)

    def locate_node_path(self):
        path = None
        if nuke:
            selected_nodes = nuke.selectedNodes()
            if selected_nodes:
                node = selected_nodes[0]
                try:
                    path = nuke.filename(node) or node['file'].value()
                except:
                    if 'file' in node.knobs():
                        path = node['file'].value()
            
            if not path:
                try:
                    path = nuke.script_directory()
                except:
                    path = ""
                
                if not path:
                    root_name = nuke.root().name()
                    if root_name != "Root":
                        path = os.path.dirname(root_name)
        
        if not path:
            return

        # Resolve path
        path = os.path.normpath(path).replace('\\', '/')
        
        # If it's a file, get folder
        if os.path.isfile(path) or not os.path.isdir(path):
            path = os.path.dirname(path)

        # Look for existing parent
        while path and not os.path.exists(path):
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
            
        if path and os.path.isdir(path):
            self.set_path(path)
            
    def path_changed(self):
        new_path = os.path.normpath(self.path_edit.currentText())
        if new_path == self.current_path:
            return
        if os.path.exists(new_path) and os.path.isdir(new_path):
            self.set_path(new_path)
            
    def on_path_selected(self, index):
        path = os.path.normpath(self.path_edit.itemText(index))
        if path == self.current_path:
            return
        if os.path.exists(path) and os.path.isdir(path):
            self.set_path(path)
            
    def tree_clicked(self, index):
        source_index = self.sidebar_proxy.mapToSource(index)
        path = os.path.normpath(self.tree_model.filePath(source_index))
        if path == self.current_path:
            return
        if os.path.isdir(path):
            self.set_path(path)
            
    def depth_changed(self, value):
        if self.config.get("max_depth") == value:
            return
        self.config["max_depth"] = value
        self.scanner.max_depth = value
        
        # Save to file
        try:
            config_path = self.get_config_path()
            nuke_dir = os.path.dirname(config_path)
            if not os.path.exists(nuke_dir):
                os.makedirs(nuke_dir)
            import json
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Failed to save depth config: {e}")
    def toggle_sidebar(self):
        visible = self.sidebar_btn.isChecked()
        self.tree_view.setVisible(visible)
        if hasattr(self, 'preview_container'):
            # Only hide the whole left panel if both are hidden
            self.left_panel.setVisible(visible or self.preview_btn.isChecked())
            
        if visible and hasattr(self, 'tree_model'):
            # Force refresh of the sidebar directory tree only
            self.tree_model.setRootPath("")
            self.tree_model.setRootPath(self.current_path)
            
            idx = self.tree_model.index(self.current_path)
            if idx.isValid() and hasattr(self, 'sidebar_proxy'):
                proxy_idx = self.sidebar_proxy.mapFromSource(idx)
                self.tree_view.setCurrentIndex(proxy_idx)
                self.tree_view.scrollTo(proxy_idx)
                
        self.save_user_settings()

    def toggle_preview(self):
        visible = self.preview_btn.isChecked()
        self.preview_container.setVisible(visible)
        # Only hide the whole left panel if both are hidden
        self.left_panel.setVisible(visible or self.sidebar_btn.isChecked())
        
        self.manage_ffmpeg_worker_state()
        
        if visible:
            self.selection_changed() # Force update when showing
        self.save_user_settings()

    def manage_ffmpeg_worker_state(self):
        if not self.ffmpeg_available:
            if self.ffmpeg_worker is not None and self.ffmpeg_worker.isRunning():
                self.ffmpeg_worker.stop()
                self.ffmpeg_worker.wait()
            return
            
        is_preview_visible = self.preview_btn.isChecked()
        if is_preview_visible:
            if self.ffmpeg_worker is None:
                self.ffmpeg_worker = FFmpegPreviewWorker(self)
                self.ffmpeg_worker.finished.connect(self.on_ffmpeg_preview_finished)
                self.ffmpeg_worker.failed.connect(self.on_ffmpeg_failed)
            if not self.ffmpeg_worker.isRunning():
                self.ffmpeg_worker.start()
        else:
            if self.ffmpeg_worker is not None and self.ffmpeg_worker.isRunning():
                self.ffmpeg_worker.stop()
                self.ffmpeg_worker.wait()

    def selection_changed(self, *args):
        if not hasattr(self, 'preview_btn') or not self.preview_btn.isChecked():
            return
            
        view = self.view_stack.currentWidget()
        indexes = view.selectionModel().selectedRows()
        if not indexes:
            self.update_preview(None)
            return
            
        # Get data from the first selected row
        proxy_idx = indexes[0]
        # Map back to source model
        source_idx = view.model().mapToSource(proxy_idx)
        item = view.model().sourceModel().data(source_idx, QtCore.Qt.UserRole)
        
        self._pending_preview_item = item
        # Debounce the preview update to avoid spamming jobs
        if hasattr(self, '_preview_debounce_timer'):
            self._preview_debounce_timer.stop()
        else:
            self._preview_debounce_timer = QtCore.QTimer()
            self._preview_debounce_timer.setSingleShot(True)
            self._preview_debounce_timer.timeout.connect(lambda: self.update_preview(self._pending_preview_item))
            
        self._preview_debounce_timer.start(150) # 150ms delay

    def update_preview(self, item):
        if not item:
            self.preview_img.clear()
            self.preview_img.setText("No selection")
            self.preview_info.setText("Select a file to see details")
            return
            
        name = item.get("name", "Unknown")
        path = item.get("path", "")
        size = item.get("size_str", "")
        owner = item.get("owner", "")
        ext = item.get("extension", "").lower()
        is_seq = item.get("is_sequence", False)
        
        # 1. Update Metadata (Condensed Layout)
        is_folder = item.get("is_folder", False)
        info_text = f"<b>{name}</b><br/>"
        details = []
        if is_seq:
            details.append("Sequence")
            frames = item.get("frames", "")
            if frames:
                details.append(f"Frames: {frames}")
        elif is_folder:
            details.append("Folder")
        else:
            details.append("File")
            
        if size:
            details.append(size)
        if owner:
            details.append(f"Owner: {owner}")
            
        info_text += " • ".join(details)
        
        self.preview_info.setText(info_text)
        
        # 2. Update Image Preview
        self.preview_img.clear()
        self.preview_img.set_item(item, self)
        
        if item.get('is_folder'):
            self.preview_img.setPixmap(FOLDER_ICON.pixmap(64, 64))
            return

        img_path = path
        if is_seq:
            try:
                # Resolve sequence to frame 2 (second frame in sequence)
                first_frame = item.get("first_frame", 0)
                last_frame = item.get("last_frame", 0)
                target_frame = first_frame + 1 if last_frame > first_frame else first_frame
                
                if '%' in img_path:
                    try: img_path = img_path % target_frame
                    except: pass
                elif '#' in img_path:
                    import re
                    def replace_hash(match):
                        return str(target_frame).zfill(len(match.group(0)))
                    img_path = re.sub(r'#+', replace_hash, img_path)
            except:
                pass
        
        # Start the background preview job
        self.start_preview_job(img_path, item)

    def start_preview_job(self, path, item=None):
        # Absolutely prevent trying to generate previews for folders/directories
        if (item and item.get("is_folder")) or (path and os.path.isdir(path)):
            self.preview_img.setPixmap(FOLDER_ICON.pixmap(64, 64))
            return
            
        # Check for standard QPixmap support first (best for JPG/PNG single files)
        is_seq = item.get("is_sequence", False) if item else False
        img_ext = os.path.splitext(path)[1].lower()
        if not is_seq and img_ext in [".jpg", ".jpeg", ".png", ".bmp", ".gif"]:
            pixmap = QtGui.QPixmap(path)
            if not pixmap.isNull():
                self.preview_img.set_single_pixmap(pixmap)
                return

        # If ffmpeg is available and its pane is active, request background preview
        if self.ffmpeg_available and self.preview_btn.isChecked() and hasattr(self, 'ffmpeg_worker') and self.ffmpeg_worker:
            is_seq = item.get("is_sequence", False) if item else False
            first_frame = item.get("first_frame", 0) if item else 0
            last_frame = item.get("last_frame", 0) if item else 0
            seq_path = item.get("path", None) if item else None
            try:
                source_mtime = item.get("date", 0) if item else os.path.getmtime(path)
            except Exception:
                source_mtime = 0
            self.ffmpeg_worker.request_preview(path, is_seq, first_frame, last_frame, seq_path, source_mtime)
        else:
            # Simple fallback to direct QPixmap loading
            pixmap = QtGui.QPixmap(path)
            if not pixmap.isNull():
                self.preview_img.set_single_pixmap(pixmap)
            else:
                self.preview_img.setPixmap(FILE_ICON.pixmap(64, 64))

    def on_ffmpeg_preview_finished(self, q_img, path, is_strip, cols):
        if q_img and not q_img.isNull():
            pixmap = QtGui.QPixmap.fromImage(q_img)
            if is_strip:
                self.preview_img.set_strip_pixmap(pixmap, cols)
            else:
                self.preview_img.set_single_pixmap(pixmap)
        else:
            self.on_ffmpeg_failed(path)

    def on_ffmpeg_failed(self, path):
        # Fallback when ffmpeg fails or is unavailable
        pixmap = QtGui.QPixmap(path)
        if not pixmap.isNull():
            self.preview_img.set_single_pixmap(pixmap)
        else:
            self.preview_img.setPixmap(FILE_ICON.pixmap(64, 64))

    def set_preview_pixmap(self, pixmap):
        if not pixmap or pixmap.isNull():
            return
        self.preview_img.set_single_pixmap(pixmap)



        
    def switch_view_mode(self, index):
        if self.view_stack.currentIndex() == index:
            # Already in this mode, toggle expansion for tree views
            view = self.view_stack.currentWidget()
            if isinstance(view, QtWidgets.QTreeView):
                if not hasattr(self, '_tree_expanded_state'):
                    self._tree_expanded_state = {}
                
                is_expanded = self._tree_expanded_state.get(index, False)
                if is_expanded:
                    view.collapseAll()
                else:
                    view.expandAll()
                self._tree_expanded_state[index] = not is_expanded
            return

        self.view_stack.setCurrentIndex(index)
        # Reset state on switch
        if not hasattr(self, '_tree_expanded_state'):
            self._tree_expanded_state = {}
        self._tree_expanded_state[index] = False
        
        self.update_active_view_data()
        self.update_filters() # Re-apply filters to the new view
        self.save_user_settings()
        self.selection_changed()
        
    def _normalize_padding(self, path):
        if not path:
            return ""
        import re
        # Ensure path is normalized and lowercase for robust comparison
        p = os.path.normpath(path).replace('\\', '/').lower()
        # Match all types of padding: ####, %04d, %d, <UDIM>, %V, %v, or literal digits
        # Replace the frame/token part right before extension with @@@@
        return re.sub(r'([._ ]?)(#+|%\d*d|\d+|<UDIM>|<udim>|%[Vv])(\.[^.\/\\]+)$', r'\1@@@@\3', p)

    def get_imported_nuke_files(self):
        imported = {}
        if not nuke:
            return imported
        for node in nuke.allNodes(recurseGroups=True):
            if 'file' in node.knobs():
                try:
                    # Use nuke.filename() to get the resolved absolute path instead of just the knob value
                    fval = nuke.filename(node)
                    if fval:
                        norm = os.path.normpath(fval).replace('\\', '/').lower()
                        imported[norm] = node.name()
                except Exception:
                    pass
        return imported

    def update_active_view_data(self):
        if not hasattr(self, 'cached_results'):
            return
            
        imported_files = self.get_imported_nuke_files()
        
        # Precompute normalized mappings for padded files
        normalized_nuke = {}
        for n_path, node_name in imported_files.items():
            normalized_nuke[self._normalize_padding(n_path)] = node_name
            
        # For base folder path checks, we need a list of all used paths
        all_used_paths = list(imported_files.keys())
            
        # Update flags for all items in current view
        for item in self.cached_results:
            path = item.get("path")
            if path:
                item["is_favorite"] = path in self.favorites
                item["imported_node_name"] = None
                
                # Normalize current item path
                norm_path = os.path.normpath(path).replace('\\', '/').lower()
                
                # 1. Check for Direct Match
                if norm_path in imported_files:
                    item["imported_node_name"] = imported_files[norm_path]
                else:
                    # 2. Check for Padded/Sequence Match
                    norm_padded = self._normalize_padding(norm_path)
                    if norm_padded in normalized_nuke:
                        item["imported_node_name"] = normalized_nuke[norm_padded]
                
                # 3. Base Folder Path Check: highlight folders that contain used files
                if not item.get("imported_node_name") and item.get("is_folder"):
                    # Ensure prefix ends with / for accurate sub-path matching
                    folder_prefix = norm_path if norm_path.endswith("/") else norm_path + "/"
                    for used_path in all_used_paths:
                        if used_path.startswith(folder_prefix):
                            item["imported_node_name"] = "In Use (Sub-folder content)"
                            break
            
        idx = self.view_stack.currentIndex()
        if idx == 0: # List
            self.list_model.update_data(self.cached_results)
        elif idx == 1: # Tree
            self.tree_main_model.update_data(self.cached_results)
        else: # Group
            self.group_model.update_data(self.cached_results)
            
    def sequence_toggle_changed(self, state):
        self.scanner.bundle_sequences = self.filter_sequences_cb.isChecked()
        self.update_filters()
        self.refresh()

    def update_filters(self, *args):
        search_text = self.search_edit.currentText()
        show_files = self.filter_files_cb.isChecked()
        show_folders = self.filter_folders_cb.isChecked()
        bundle_sequences = self.filter_sequences_cb.isChecked()
        
        # Only update the active proxy
        idx = self.view_stack.currentIndex()
        if idx == 0:
            proxy = self.list_proxy
        elif idx == 1:
            proxy = self.tree_proxy
        else:
            proxy = self.group_proxy
        
        # Robust multi-word search
        proxy.set_search_text(search_text)
        proxy.show_files = show_files
        proxy.show_folders = show_folders
        proxy.sort_used_first = self.sort_used_first_cb.isChecked()
        if hasattr(proxy, 'setRecursiveFilteringEnabled'):
            # Multi-level filtering needed for Tree (idx 1) and Group (idx 2)
            proxy.setRecursiveFilteringEnabled(idx in [1, 2]) 
        proxy.invalidate()
        
        if search_text:
            self.search_edit.lineEdit().setStyleSheet("background-color: #5a3b00; color: #ffffff;")
        else:
            self.search_edit.lineEdit().setStyleSheet("")
            
        show_files = self.filter_files_cb.isChecked()
        show_folders = self.filter_folders_cb.isChecked()
        
        if show_files:
            self.filter_files_cb.setStyleSheet("color: #ff8800; font-weight: bold;")
        else:
            self.filter_files_cb.setStyleSheet("")

        if show_folders:
            self.filter_folders_cb.setStyleSheet("color: #ff8800; font-weight: bold;")
        else:
            self.filter_folders_cb.setStyleSheet("")

        if bundle_sequences:
            self.filter_sequences_cb.setStyleSheet("color: #ff8800; font-weight: bold;")
        else:
            self.filter_sequences_cb.setStyleSheet("")
            
        if self.sort_used_first_cb.isChecked():
            self.sort_used_first_cb.setStyleSheet("color: #ff8800; font-weight: bold;")
        else:
            self.sort_used_first_cb.setStyleSheet("")

    def store_search_history(self):
        text = self.search_edit.currentText().strip()
        if not text:
            return
            
        if text in self.search_history:
            self.search_history.remove(text)
        self.search_history.insert(0, text)
        self.search_history = self.search_history[:25]
        
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.addItems(self.search_history)
        self.search_edit.setEditText(text)
        self.search_edit.blockSignals(False)
        self.save_user_settings()
        
    def set_path(self, path):
        self.current_path = os.path.normpath(path)
        
        # Update sticky history (limit 25)
        if self.current_path in self.history:
            self.history.remove(self.current_path)
            
        # Only add to history if it's NOT in favorites (to avoid redundant dropdown entries)
        if self.current_path not in self.favorites:
            self.history.insert(0, self.current_path)
            self.history = self.history[:self.config.get("history_limit", 15)] 
        
        # Update UI path editing component (Combined History + Favorites)
        self.path_edit.blockSignals(True)
        self.path_edit.clear()
        
        # 1. Add All Favorites with star icon (up to limit)
        fav_limit = self.config.get("favorites_limit", 20)
        for i, fav_path in enumerate(self.favorites):
            if i >= fav_limit:
                break
            self.path_edit.addItem(STAR_ICON, os.path.normpath(fav_path))
            
        # 2. Add History with folder icon
        for hist_path in self.history:
            # Avoid showing the same path twice if it's both a favorite and current
            if hist_path not in self.favorites:
                self.path_edit.addItem(FOLDER_ICON, hist_path)
        
        self.path_edit.setEditText(self.current_path)
        self.path_edit.blockSignals(False)
        
        idx = self.tree_model.index(self.current_path)
        if idx.isValid():
            proxy_idx = self.sidebar_proxy.mapFromSource(idx)
            self.tree_view.setCurrentIndex(proxy_idx)
            self.tree_view.scrollTo(proxy_idx)
        
        self.refresh()
        
    def refresh(self):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scanner.stop()
            self.scan_worker.wait()
            
        # Flush cache: clear results and update UI to show empty state
        self.cached_results = []
        self.update_active_view_data()
        
        # Force refresh of the sidebar directory tree
        if hasattr(self, 'tree_model'):
            self.tree_model.setRootPath("")
            self.tree_model.setRootPath(self.current_path)
            
        # Recreate scanner to ensure fresh thread pool and settings
        self.scanner = FileScanner(self.config)
        
        self.status_label.setText("Flushing cache & Scanning...")
        self.progress_bar.setRange(0, 0) # Indeterminate until first progress update
        self.progress_bar.show()
        
        worker = ScanWorker(self.scanner, self.current_path, self)
        self.scan_worker = worker
        worker.scan_finished.connect(self.on_scan_finished)
        
        # Use a small wrapper to restore range when progress starts
        def update_progress(v):
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(v)
            
        worker.progress_updated.connect(update_progress)
        worker.start()
        
    def on_scan_finished(self, results):
        self.cached_results = results
        
        # Show loading until it finishes highlighting used files
        self.status_label.setText("Highlighting used files...")
        self.progress_bar.setRange(0, 0) # Indeterminate during highlighting
        QtWidgets.QApplication.processEvents()
        
        self.update_active_view_data()
        
        self.status_label.setText(f"Found {len(results)} items in {self.current_path}")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        # Small delay before hiding progress bar
        QtCore.QTimer.singleShot(800, self.progress_bar.hide)
        
    def table_double_clicked(self, index):
        view = self.view_stack.currentWidget()
        proxy = view.model()
        source_index = proxy.mapToSource(index)
        
        if isinstance(view, QtWidgets.QTreeView):
            node = source_index.internalPointer()
            # If it's a dummy folder or group node, ignore double click on name
            item = node._data if node else None
        else:
            item = self.list_model.data(source_index, QtCore.Qt.UserRole)
            
        if not item:
            return
            
        if item.get("is_folder") and item.get("path"):
            self.set_path(item["path"])
        elif not item.get("is_folder") and item.get("path"):
            self.load_in_nuke(item)
            
    def show_context_menu(self, pos):
        view = self.view_stack.currentWidget()
        proxy = view.model()
        indexes = view.selectionModel().selectedRows()
        if not indexes:
            return
            
        menu = QtWidgets.QMenu(self)
        
        load_action = menu.addAction(f"Load {len(indexes)} Selected Item(s)")
        
        # Add Favorite Action only if one item is selected
        fav_action = None
        zoom_action = None
        if len(indexes) == 1:
            source_index = proxy.mapToSource(indexes[0])
            if isinstance(view, QtWidgets.QTreeView):
                node = source_index.internalPointer()
                item = node._data if node else None
            else:
                item = self.list_model.data(source_index, QtCore.Qt.UserRole)
            
            if item:
                if item.get("is_folder"):
                    f_path = item.get("path")
                    if f_path in self.favorites:
                        fav_action = menu.addAction(STAR_ICON, "Remove from Favorites")
                    else:
                        fav_action = menu.addAction(STAR_ICON, "Add to Favorites")
                
                if item.get("imported_node_name"):
                    zoom_action = menu.addAction("Zoom to Node")
        
        explorer_action = menu.addAction("Open in Explorer")
        copy_path_action = menu.addAction("Copy Path")
        
        # Add Rename/Delete if enabled
        rename_action = None
        delete_action = None
        if self.config.get("enable_delete_rename", False):
            menu.addSeparator()
            if len(indexes) == 1:
                rename_action = menu.addAction("Rename Item")
            delete_action = menu.addAction(f"Delete {len(indexes)} Selected Item(s)")
        
        action = menu.exec_(view.viewport().mapToGlobal(pos))
        
        if action == load_action:
            total = len(indexes)
            self.status_label.setText(f"Loading {total} items...")
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            
            for i, idx in enumerate(indexes):
                source_index = proxy.mapToSource(idx)
                if isinstance(view, QtWidgets.QTreeView):
                    node = source_index.internalPointer()
                    item = node._data if node else None
                else:
                    item = self.list_model.data(source_index, QtCore.Qt.UserRole)
                
                # Check for is_folder to avoid loading "Group" header nodes
                if item and not item.get("is_folder"):
                    self.load_in_nuke(item)
                
                self.progress_bar.setValue(i + 1)
                QtWidgets.QApplication.processEvents()
            
            self.status_label.setText(f"Successfully loaded {total} items.")
            # Small delay before hiding
            QtCore.QTimer.singleShot(1000, self.progress_bar.hide)
            QtCore.QTimer.singleShot(2000, lambda: self.status_label.setText("Ready"))
            
        elif action == explorer_action:
            source_index = proxy.mapToSource(indexes[0])
            if isinstance(view, QtWidgets.QTreeView):
                node = source_index.internalPointer()
                item = node._data if node else None
            else:
                item = self.list_model.data(source_index, QtCore.Qt.UserRole)
                
            if item:
                path = item.get("path", "")
                self.open_in_explorer(path)
                
        elif fav_action and action == fav_action:
            source_index = proxy.mapToSource(indexes[0])
            if isinstance(view, QtWidgets.QTreeView):
                node = source_index.internalPointer()
                item = node._data if node else None
            else:
                item = self.list_model.data(source_index, QtCore.Qt.UserRole)
            
            # Add folders only if the item has an actual path
            f_path = item.get("path") if item else None
            if f_path and item.get("is_folder"):
                if f_path in self.favorites:
                    self.favorites.remove(f_path)
                else:
                    self.favorites.append(f_path)
                self.save_user_settings()
                self.rebuild_favorites_ui()
                self.update_active_view_data()

        elif zoom_action and action == zoom_action:
            if item and item.get("imported_node_name") and nuke:
                node_name = item.get("imported_node_name")
                node = nuke.toNode(node_name)
                if node:
                    for n in nuke.allNodes(recurseGroups=True):
                        n.setSelected(False)
                    node.setSelected(True)
                    nuke.zoom(1.0, [float(node.xpos()), float(node.ypos())])

        elif action == copy_path_action:
            paths = []
            for idx in indexes:
                source_index = proxy.mapToSource(idx)
                if isinstance(view, QtWidgets.QTreeView):
                    node = source_index.internalPointer()
                    item = node._data if node else None
                else:
                    item = self.list_model.data(source_index, QtCore.Qt.UserRole)
                    
                if item:
                    path = item.get("path")
                    if path:
                        paths.append(path)
            
            if paths:
                self.copy_to_clipboard("\n".join(paths))

        elif rename_action and action == rename_action:
            self.handle_rename(indexes[0])
            
        elif delete_action and action == delete_action:
            self.handle_delete(indexes)

    def handle_rename(self, proxy_index):
        view = self.view_stack.currentWidget()
        proxy = view.model()
        source_index = proxy.mapToSource(proxy_index)
        
        if isinstance(view, QtWidgets.QTreeView):
            node = source_index.internalPointer()
            item = node._data if node else None
        else:
            item = self.list_model.data(source_index, QtCore.Qt.UserRole)
            
        if not item: return
        
        old_path = item.get("path")
        if not old_path: return
        
        # Determine autofill (without padding/extension as requested)
        if item.get("is_sequence"):
            import re
            pattern = item.get("name", "")
            match = re.search(r"^(.*?)([._ ]?)(#+|%\d*d)(\.[^.]+)$", pattern)
            autofill_name = match.group(1) if match else pattern
        elif item.get("is_folder"):
            autofill_name = os.path.basename(old_path)
        else:
            # File
            autofill_name = os.path.splitext(os.path.basename(old_path))[0]
            
        dialog = RenameDialog(autofill_name, self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
            
        new_name = dialog.get_text()
        if not new_name or new_name == autofill_name:
            return
            
        try:
            parent_dir = os.path.dirname(old_path)
            if item.get("is_sequence"):
                # Sequence rename: rename all frames
                # This is complex because we need to replace the prefix in the pattern
                # Let's use a simpler approach: regex replace the prefix
                import re
                # Pattern is like prefix.%04d.ext
                # We want to change the prefix
                # Sequence patterns in scanner use %0nd
                pattern = item.get("name") # e.g. "shot_v001.####.exr"
                match = re.search(r"^(.*?)([._ ]?)(#+|%\d*d)(\.[^.]+)$", pattern)
                if not match:
                    QtWidgets.QMessageBox.warning(self, "Rename Error", "Could not parse sequence pattern for renaming.")
                    return
                
                old_prefix, old_sep, old_token, old_ext = match.groups()
                
                # Parse new name to see if user kept/changed the pattern
                new_match = re.search(r"^(.*?)([._ ]?)(#+|%\d*d)(\.[^.]+)$", new_name)
                if new_match:
                    new_prefix, new_sep, new_token, new_ext = new_match.groups()
                    # Determine new padding length
                    if "#" in new_token:
                        new_pad = len(new_token)
                    else:
                        try: new_pad = int(re.search(r"\d+", new_token).group())
                        except: new_pad = len(old_token) if "#" in old_token else 1
                else:
                    # Treat as new prefix only
                    new_prefix = new_name
                    new_sep = old_sep
                    new_pad = len(old_token) if "#" in old_token else 4
                    new_ext = old_ext

                # Find and rename files
                files_to_rename = []
                for f in os.listdir(parent_dir):
                    if f.startswith(old_prefix) and f.endswith(old_ext):
                        f_match = re.match(rf"^{re.escape(old_prefix)}{re.escape(old_sep)}(\d+){re.escape(old_ext)}$", f)
                        if f_match:
                            files_to_rename.append((f, f_match.group(1)))
                            
                total_files = len(files_to_rename)
                if total_files > 0:
                    self.status_label.setText(f"Renaming {total_files} files...")
                    self.progress_bar.setRange(0, total_files)
                    self.progress_bar.setValue(0)
                    self.progress_bar.show()
                    
                count = 0
                for i, (f, frame_num) in enumerate(files_to_rename):
                    new_frame = frame_num.zfill(new_pad)
                    f_old = os.path.join(parent_dir, f)
                    f_new = os.path.join(parent_dir, f"{new_prefix}{new_sep}{new_frame}{new_ext}")
                    
                    if f_old != f_new:
                        os.rename(f_old, f_new)
                        count += 1
                        
                    if i % 10 == 0:
                        self.progress_bar.setValue(i + 1)
                        QtWidgets.QApplication.processEvents()
                        
                if total_files > 0:
                    self.progress_bar.setValue(total_files)
                    QtCore.QTimer.singleShot(1000, self.progress_bar.hide)
                
                self.status_label.setText(f"Renamed {count} files in sequence to '{new_prefix}'")
            else:
                # Single file/folder rename
                if not item.get("is_folder"):
                    old_path_ext = os.path.splitext(old_path)[1]
                    if not new_name.lower().endswith(old_path_ext.lower()):
                        new_name += old_path_ext
                        
                new_path = os.path.join(parent_dir, new_name)
                os.rename(old_path, new_path)
                self.status_label.setText(f"Renamed '{os.path.basename(old_path)}' to '{new_name}'")
            
            self.refresh()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Rename Error", f"Failed to rename:\n{e}")

    def handle_delete(self, proxy_indexes):
        view = self.view_stack.currentWidget()
        proxy = view.model()
        
        items_to_delete = []
        used_items_info = [] # List of (item_name, usage_info)
        
        # Get current imported files in Nuke for absolute safety
        imported_files = self.get_imported_nuke_files()
        
        for idx in proxy_indexes:
            source_index = proxy.mapToSource(idx)
            if isinstance(view, QtWidgets.QTreeView):
                node = source_index.internalPointer()
                item = node._data if node else None
            else:
                item = self.list_model.data(source_index, QtCore.Qt.UserRole)
            
            if not item:
                continue
            items_to_delete.append(item)
            
            # Check if this item is used
            node_name = item.get("imported_node_name")
            if node_name:
                used_items_info.append((item.get("name"), f"Used by: {node_name}"))
            elif item.get("has_imported"):
                used_items_info.append((item.get("name"), "Folder contains used media"))
            elif item.get("is_folder") and item.get("path"):
                # Deeper check for folders just in case scanner hasn't reached children
                folder_path = os.path.normpath(item["path"]).replace('\\', '/') + "/"
                for n_path, n_node in imported_files.items():
                    if n_path.startswith(folder_path):
                        used_items_info.append((item.get("name"), "Folder contains used media"))
                        break
                
        if not items_to_delete: return
        
        if used_items_info:
            warning_msg = "\n\nCRITICAL WARNING: The following items are currently USED in Nuke:\n"
            for name, info in used_items_info:
                warning_msg += f" • {name} ({info})\n"
            
            msg = f"PERMANENT DELETE WARNING\n\nYou are about to delete {len(items_to_delete)} item(s).{warning_msg}\nDeleting these will break Read nodes in your current Nuke script.\n\nAre you absolutely sure you want to proceed?"
            res = QtWidgets.QMessageBox.critical(self, "Confirm Delete - USED MEDIA DETECTED", msg, 
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        else:
            msg = f"Are you sure you want to PERMANENTLY delete {len(items_to_delete)} item(s)?\n\nThis cannot be undone!"
            res = QtWidgets.QMessageBox.warning(self, "Confirm Delete", msg, 
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

        if res != QtWidgets.QMessageBox.Yes:
            return
            
        errors = []
        deleted_count = 0
        total_files = 0
        
        total_items = len(items_to_delete)
        if total_items > 0:
            self.status_label.setText(f"Deleting {total_items} items...")
            self.progress_bar.setRange(0, total_items)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
        
        for i, item in enumerate(items_to_delete):
            path = item.get("path")
            if not path: continue
            
            try:
                if item.get("is_sequence"):
                    # Delete all files in sequence
                    import re
                    parent_dir = os.path.dirname(path)
                    pattern = item.get("name")
                    match = re.search(r"^(.*?)([._ ]?)(#+|%\d*d)(\.[^.]+)$", pattern)
                    if match:
                        prefix, sep, token, ext = match.groups()
                        
                        for f_idx, f in enumerate(os.listdir(parent_dir)):
                            if f.startswith(prefix) and f.endswith(ext):
                                f_match = re.match(rf"^{re.escape(prefix)}{re.escape(sep)}(\d+){re.escape(ext)}$", f)
                                if f_match:
                                    os.remove(os.path.join(parent_dir, f))
                                    total_files += 1
                                    
                            if f_idx % 50 == 0:
                                QtWidgets.QApplication.processEvents()
                    deleted_count += 1
                elif item.get("is_folder"):
                    self.status_label.setText(f"Deleting folder {os.path.basename(path)}...")
                    QtWidgets.QApplication.processEvents()
                    shutil.rmtree(path)
                    deleted_count += 1
                else:
                    os.remove(path)
                    deleted_count += 1
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
                
            self.progress_bar.setValue(i + 1)
            QtWidgets.QApplication.processEvents()
            
        if total_items > 0:
            QtCore.QTimer.singleShot(1000, self.progress_bar.hide)
            
        if errors:
            QtWidgets.QMessageBox.critical(self, "Delete Errors", "Some items could not be deleted:\n\n" + "\n".join(errors))
        
        self.status_label.setText(f"Deleted {deleted_count} items ({total_files} total files)")
        self.refresh()

    def copy_to_clipboard(self, text):
        cb = QtWidgets.QApplication.clipboard()
        cb.setText(text, QtGui.QClipboard.Clipboard)
        self.status_label.setText(f"Copied to clipboard: {text[:50]}..." if len(text) > 50 else f"Copied to clipboard: {text}")

    def open_in_explorer(self, path):
        if not path or not os.path.exists(path):
            # Try getting dirname if it's a sequence/file path that doesn't literally exist
            path = os.path.dirname(path)
            if not path or not os.path.exists(path):
                return
                
        # If it's a file, we want the folder
        if os.path.isfile(path):
            folder_path = os.path.dirname(path)
        else:
            folder_path = path

        import subprocess
        if sys.platform == 'win32':
            os.startfile(folder_path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', folder_path])
        else:
            subprocess.Popen(['xdg-open', folder_path])
                    
    def load_in_nuke(self, item):
        if not nuke:
            print(f"Not in Nuke. Would load: {item['path']}")
            return
            
        path = item.get('path', '')
        ext = item.get('extension', '').lower()
        
        # Determine the appropriate Nuke node type
        audio_exts = ['.wav', '.mp3', '.aiff', '.aif']
        geo_exts = ['.abc', '.fbx', '.obj']
        
        node_type = 'Read'
        if ext in audio_exts:
            node_type = 'AudioRead'
        elif ext in geo_exts:
            node_type = 'ReadGeo2'
            
        try:
            # Create the node
            read_node = nuke.createNode(node_type)
            # Use fromUserText to handle path formatting correctly
            read_node['file'].fromUserText(path)
            
            # For standard Read nodes, handle frame range if it's a sequence
            if node_type == 'Read' and item.get('is_sequence'):
                first = item.get('first_frame')
                last = item.get('last_frame')
                if first is not None and last is not None:
                    read_node['first'].setValue(int(first))
                    read_node['last'].setValue(int(last))
            
            print(f"Created {node_type} node for {item['name']}.")
            
        except Exception as e:
            print(f"Error creating {node_type} node for {path}: {e}")
            # Fallback to basic creation if it failed
            try:
                nuke.createNode('Read', f'file {{{path}}}')
            except:
                pass


def start_kadatha():
    return Kadatha()

# Registration code for Nuke
if nukescripts:
    try:
        nukescripts.panels.registerWidgetAsPanel(
            'kadatha.start_kadatha', 
            'Kadatha', 
            'com.Headshift.Kadatha'
        )
        print("Kadatha panel registered successfully.")
    except Exception as e:
        print(f"Could not register Kadatha panel: {e}")
