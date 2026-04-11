# Kadatha - File Browser for Nuke

**Version:** 1.1.0  
**License:** Apache 2.0  
**Developed for:** Nuke  
**Author:** [Prasannakumar T Bhat](https://github.com/pbhat99)  
**Based on:** Original code by [Sam Richards](https://github.com/richardssam) (FileSystem browser for xSTUDIO)

---

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Getting Started](#getting-started)
- [Interface Overview](#interface-overview)
- [Features](#features)
  - [Three View Modes](#three-view-modes)
  - [File Preview](#file-preview)
  - [Search and Filtering](#search-and-filtering)
  - [Favorites](#favorites)
  - [Loading Files into Nuke](#loading-files-into-nuke)
  - [Drag and Drop](#drag-and-drop)
  - [Context Menu Actions](#context-menu-actions)
  - [Rename and Delete](#rename-and-delete)
  - [Configuration](#configuration)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Troubleshooting](#troubleshooting)
- [Configuration File](#configuration-file)
- [File Format Support](#file-format-support)

---

## Overview

Kadatha is a powerful file browser panel designed specifically for Nuke. It provides an intuitive interface for browsing, previewing, and loading image sequences, video files, 3D geometry, and audio files directly into your Nuke compositions. With advanced features like sequence bundling, version grouping, real-time preview, and powerful search capabilities, Kadatha streamlines your VFX and compositing workflow.

### Key Capabilities

- **Multi-format support:** EXR, DPX, PNG, JPG, MOV, MP4, ABC, FBX, OBJ, WAV, and more
- **Sequence bundling:** Automatically groups numbered files into frame ranges
- **Version detection:** Identifies and groups different versions of the same asset
- **Real-time preview:** Hover over sequences to preview frame playback
- **Nuke integration:** Import files directly, locate nodes, and zoom to imported assets
- **Threaded scanning:** Fast, non-blocking directory scans with progress feedback

---

## Installation

### Prerequisites

- Nuke 15 or later (PySide6 required)
- Python 3.x (bundled with Nuke)
- Optional: OpenImageIO (OIIO) for enhanced image preview

### Installation Steps

1. **Copy the Kadatha folder** to your `.nuke` directory:
   ```
   ~/.nuke/Kadatha
   ```

2. **Ensure the following files** are present in the Kadatha folder:
   - `kadatha.py` - Main application code
   - `scanner.py` - File scanning engine
   - `menu.py` - Nuke menu integration
   - `Icons/` - Icon assets

3. **Register the panel** (usually handled by `menu.py`):
   ```python
   import kadatha
   nukescripts.panels.registerWidgetAsPanel(
       'kadatha.start_kadatha',
       'Kadatha',
       'com.Headshift.Kadatha'
   )
   ```

4. **Restart Nuke** or reload the panel from the Nuke menu.

---

## Getting Started

### Opening Kadatha

Once installed, Kadatha appears as a dockable panel in Nuke. Access it via:
- **Menu:** `Pane > Kadatha` (or wherever your menu integration places it)
- **Python:** Run `kadatha.start_kadatha()` in the Script Editor

### Initial Navigation

1. **Browse directories** using the **Directory Tree** on the left panel
2. **Enter a path** manually in the **Address Bar** at the top
3. **Click "Locate"** to jump to the folder of your currently selected Nuke node
4. **Use the "Up" button** to navigate to the parent directory

### Scanning Files

Kadatha automatically scans the current directory when you navigate. The scan depth can be adjusted using the **Depth** spinbox (0 = current folder only, higher values include subdirectories).

---

## Interface Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ [Up] [Address Bar ▼] [Depth] [Locate] [Refresh]                │
├─────────────────────────────────────────────────────────────────┤
│ [Sidebar] [Preview] Search: [Filter String...] [Folders]       │
│ [Files] [Sequence] [Config]                                     │
├─────────────────────────────────────────────────────────────────┤
│ ★ [Favorite 1] ★ [Favorite 2] ★ [Favorite 3] ...               │
├──────────────────┬──────────────────────────────────────────────┤
│                  │                                              │
│  Directory Tree  │           File List/Tree/Group View          │
│  (Sidebar)       │           (Main content area)                │
│                  │                                              │
│                  ├──────────────────────────────────────────────┤
│                  │          File Preview Panel                  │
│                  │          [Image/Sequence Preview]            │
│                  │          File Details                        │
│                  │                                              │
├──────────────────┴──────────────────────────────────────────────┤
│ Found 124 items  [List] [Tree] [Group]                         │
├─────────────────────────────────────────────────────────────────┤
│ [████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░] Progress  │
└─────────────────────────────────────────────────────────────────┘
```

### Top Bar

- **Up:** Navigate to parent directory
- **Address Bar:** Combined history/favorites dropdown. Type a path and press Enter, or select from history
- **Depth:** Subdirectory scan depth (0 = current folder only)
- **Locate:** Jump to the folder of the selected Nuke node or current script
- **Refresh:** Force-rescan the current directory

### Filter Bar

- **Sidebar:** Toggle the directory tree panel
- **Preview:** Toggle the file preview panel
- **Search:** Filter files by name with advanced boolean logic
- **Folders:** Toggle folder visibility
- **Files:** Toggle file visibility
- **Sequence:** Enable/disable sequence bundling
- **Config:** Open configuration dialog

### Favorites Bar

Quick-access buttons for your favorite directories. Right-click any favorite button to remove it.

### Main Content Area

Displays files and folders in three interchangeable view modes (see below).

### Preview Panel

Shows metadata and thumbnail previews of selected files. For sequences, hover your mouse over the preview image to play a frame preview animation.

---

## Features

### Three View Modes

Switch between views using the buttons at the bottom of the panel:

#### 1. List View
Flat list of files and folders in the current directory. Ideal for quick browsing of single directories.

**Columns:**
- **Name:** File or sequence name (with icons)
- **Version:** Detected version number (e.g., `v003`)
- **Frames:** Frame range for sequences
- **Owner:** File owner/username
- **Date:** Last modified timestamp
- **Size:** File or total sequence size

#### 2. Tree View
Hierarchical tree showing files across all scanned subdirectories. Useful for exploring deeply nested project structures without navigating manually.

#### 3. Group View
Aggregated view that groups all versions of the same file together. Each group header shows a summary with the number of versions and metadata from the latest version. Expand groups to see individual versions with their directory paths.

### File Preview

Select any file to see:
- **Thumbnail preview** (uses OpenImageIO for EXR/DPX, Qt for JPG/PNG, and OpenCV for video formats)
- **Metadata:** Name, type, size, owner, frame range
- **Sequence playback:** Hover your mouse over the preview image of a sequence to animate through frames (~10 fps)

**Preview Performance Tips:**
- OIIO provides the fastest previews for EXR and DPX files
- Video files (MOV, MP4) may take slightly longer to generate previews
- A 150ms debounce delay prevents preview spam during rapid selection

### Search and Filtering

Kadatha features an advanced search system with boolean logic:

#### Basic Search
Type in the search box to filter files by name (case-insensitive).

#### Exclusion (`-`)
Prefix a term with `-` to exclude it:
```
plate-temp     # Find files containing "plate-temp"
-temp          # Exclude files containing "temp"
```

#### AND Logic (`+`)
Combine terms with `+` to require all of them:
```
plate+low      # Find files containing BOTH "plate" AND "low"
comp+v03       # Find files with "comp" AND "v03"
```

#### OR Logic (spaces)
Separate terms with spaces to match any of them:
```
plate bg       # Find files containing "plate" OR "bg"
```

#### Combined Example
```
plate+low -temp v01    # Match (plate AND low) OR v01, but exclude temp
```

**Visual Feedback:** The search box turns orange when a filter is active. Active filter checkboxes are highlighted in orange.

### Favorites

Add directories to your favorites for quick access:

- **Add:** Right-click a folder in the main view → "Add to Favorites"
- **Navigate:** Click a favorite button in the favorites bar
- **Remove:** Right-click a favorite button → "Remove from Favorites"

Favorites appear both in the favorites bar and at the top of the address bar dropdown (marked with a ★ icon).

### Loading Files into Nuke

#### Single File/Sequence
Double-click any file to create a Nuke node automatically. Kadatha determines the appropriate node type:
- **Read:** Standard image files and sequences (EXR, DPX, PNG, etc.)
- **AudioRead:** Audio files (WAV, MP3, AIFF)
- **ReadGeo2:** Geometry files (ABC, FBX, OBJ)

For sequences, Kadatha automatically sets the correct frame range.

#### Multiple Files
Select multiple files (Ctrl/Cmd+Click or Shift+Click), then right-click → "Load X Selected Item(s)". Kadatha creates nodes for all selected files with a progress indicator.

#### Imported File Highlighting
Files currently imported in your Nuke script are highlighted in **orange** in the file list. Hover over them to see which node is using them, or right-click → "Zoom to Node" to locate them in your node graph.

### Drag and Drop

Kadatha supports drag-and-drop out of the box:
- **Drag files** from the Kadatha list/tree directly into your Nuke node graph
- **Drag files** to other applications that accept file URIs
- All selected files are included in the drag operation

### Context Menu Actions

Right-click on files or folders to access:

- **Load X Selected Item(s):** Import into Nuke
- **Add/Remove from Favorites:** Manage favorites
- **Zoom to Node:** (If file is imported) Jump to the using node in Nuke
- **Open in Explorer:** Open the containing folder in your OS file explorer
- **Copy Path:** Copy the full file path to clipboard
- **Rename Item:** (If enabled in config) Rename the file/sequence
- **Delete X Selected Item(s):** (If enabled in config) Permanently delete files

### Rename and Delete

**Note:** These actions are **disabled by default** for safety. Enable them in the Configuration dialog (`Config` button → "File Mutations" checkbox).

#### Rename
- Select a single file or sequence
- Right-click → "Rename Item"
- For sequences, enter a new prefix. You can also change padding by including `####` or `%04d` tokens
- Example: `shot_v001.%04d.exr` → `myshot_v002.%04d.exr` renames all frames

#### Delete
- Select one or more items
- Right-click → "Delete X Selected Item(s)"
- Confirm the action in the dialog
- **Warning:** Deletion is permanent and cannot be undone!

### Configuration

Access the Configuration dialog via the **Config** button in the filter bar.

#### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **Extensions** | File extensions to include in scans | `.mov, .mp4, .mkv, .exr, .jpg, .jpeg, .png, .dpx, .tiff, .tif, .wav, .mp3, .abc, .fbx, .obj` |
| **Ignore List** | Directories and files to ignore | `.git, .quarantine, eryx_unreal_plugin, .DS_Store, cache, rendergallery.db, rendergallery` |
| **Single Files** | Extensions that should never be bundled as sequences | `.mov, .mp4, .abc, .fbx, .obj, .wav, .mp3` |
| **Default Depth** | Default subdirectory scan depth | `0` |
| **Thread Count** | Number of scan threads (1-16) | `4` |
| **Address Bar History** | Maximum history entries | `15` |
| **Address Bar Favorites** | Maximum favorites shown in address bar | `20` |
| **Version Regex** | Regular expression to detect version numbers | `[._]v(\d+)\|v(\d+)` |
| **File Mutations** | Enable rename and delete in context menu | `False` (disabled) |

#### Factory Reset

Click **Factory Reset** in the config dialog to wipe all settings, favorites, history, and layouts. This is irreversible!

---

## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Navigate to path | Type in Address Bar + `Enter` |
| Commit search term to history | Type in Search + `Enter` |
| Select multiple files | `Ctrl/Cmd + Click` or `Shift + Click` |
| Select all files | `Ctrl/Cmd + A` (in file view) |
| Deselect all | `Esc` |

---

## Troubleshooting

### Issue: "PySide6 is not available"
**Solution:** Ensure you're running Kadatha inside Nuke 15 or later, which includes PySide6. If using an older Nuke version, Kadatha attempts to fall back to PySide2.

### Issue: No files showing in scan
**Solutions:**
- Check that the file extensions are included in your **Extensions** config
- Verify the directories aren't in the **Ignore List**
- Increase the **Depth** value to scan subdirectories
- Click **Refresh** to force a rescan

### Issue: Preview not showing for certain files
**Solutions:**
- Ensure OpenImageIO is available for EXR/DPX preview (usually bundled with Nuke)
- Video files use a subprocess preview generator; check that Python can execute subprocesses
- Large files may take a moment to generate previews (150ms debounce + processing time)

### Issue: Imported files not highlighted in orange
**Solution:** The file path in Nuke's Read nodes must match the scanned path exactly. Path normalization handles padding differences (e.g., `%04d` vs `####`), but drive letters or network path differences may prevent matching.

### Issue: Scan seems slow or freezes
**Solution:** 
- Reduce the **Thread Count** if you're experiencing system slowdowns
- Lower the **Depth** to limit subdirectory scanning
- Add unnecessary directories to the **Ignore List**
- Large directories with thousands of files naturally take longer

### Issue: Sequences not bundling correctly
**Solution:** 
- Ensure the **Sequence** checkbox is enabled
- Check that file extensions aren't in the **Single Files** list
- Verify files follow a numbered pattern (e.g., `shot.0001.exr`, `shot.0002.exr`)

---

## Configuration File

Kadatha stores settings in two locations:

### 1. JSON Configuration
**Location:** `~/.nuke/Kadatha_config.json`

Stores scan settings, extensions, ignore lists, and version regex. Example:
```json
{
    "extensions": [".mov", ".mp4", ".exr", ".png", ".jpg", ".dpx"],
    "ignore_dirs": [".git", ".DS_Store", "cache"],
    "non_sequence_extensions": [".mov", ".mp4", ".abc"],
    "max_depth": 0,
    "thread_count": 4,
    "version_regex": "[._]v(\\d+)|v(\\d+)",
    "bundle_sequences": true,
    "enable_delete_rename": false
}
```

### 2. INI User Settings
**Location:** `~/.nuke/Kadatha_Settings.ini`

Stores user-specific data: favorites, history, search history, layout sizes, sort preferences, and view state. This file is automatically updated when you close or hide the panel.

### Example Configuration File
A sample configuration is provided: `kadatha_config.json.example`

---

## File Format Support

### Image Sequences
- **OpenEXR (.exr):** Industry-standard HDR format. Best preview performance with OIIO
- **DPX (.dpx):** Digital Picture Exchange. Commonly used in film pipelines
- **PNG (.png):** Portable Network Graphics
- **JPEG (.jpg, .jpeg):** Standard photographic format
- **TIFF (.tiff, .tif):** Tagged Image File Format

### Video Files
- **QuickTime (.mov):** Apple's video container
- **MP4 (.mp4):** MPEG-4 Part 14
- **Matroska (.mkv):** Open-source video container

### 3D Geometry
- **Alembic (.abc):** Interchange format for 3D data
- **FBX (.fbx):** Autodesk's 3D exchange format
- **OBJ (.obj):** Wavefront 3D object format

### Audio Files
- **WAV (.wav):** Uncompressed audio
- **MP3 (.mp3):** Compressed audio
- **AIFF (.aif, .aiff):** Audio Interchange File Format

---

## Advanced Tips

### Version Detection
Kadatha automatically detects version numbers using the regex pattern `[._]v(\d+)|v(\d+)`. This matches patterns like:
- `shot_v001.exr`
- `comp_final_v003.exr`
- `plate_v15.exr`

Versions are displayed in the **Version** column as `v001`, `v003`, etc., and can be sorted to find the latest version quickly.

### Sequence Padding Detection
Kadatha identifies frame numbers and padding automatically:
- `shot.0001.exr` → 4-digit padding (`####`)
- `shot.1.exr` → 1-digit padding
- `shot.%04d.exr` → Standard printf format

When renaming sequences, you can change the padding by modifying the token in the new name.

### Locating Imported Files
Files already imported into Nuke appear in **orange** in the file list. This helps you:
- Avoid loading duplicate nodes
- Find where assets are used in your script
- Quickly navigate to nodes in complex scripts (right-click → "Zoom to Node")

### Performance Optimization
- **Lower thread count** on less powerful machines (1-2 threads)
- **Increase thread count** on multi-core systems for faster scans (8-16 threads)
- **Use Depth = 0** for large root directories to avoid scanning everything
- **Disable Preview panel** when not needed to reduce processing overhead

---

## Support and Contributing

- **Issues & Bug Reports:** [GitHub Issues](https://github.com/pbhat99/Kadatha/issues)
- **Source Code:** [GitHub Repository](https://github.com/pbhat99/Kadatha)
- **License:** Apache 2.0

Contributions are welcome! Feel free to submit pull requests or feature requests.

---

## Changelog

### Version 1.1.0
- Enhanced preview system with background worker threads
- OpenCV support for video and image formats
- Improved sequence playback on hover
- Advanced boolean search with `+` and `-` operators
- Factory reset functionality in config dialog
- Orange highlighting for imported Nuke files
- Zoom to Node context menu action
- Layout state persistence (column widths, sort order, splitter sizes)
- Search history tracking
- Drag-and-drop support for files
- Multi-file loading with progress indicator
- Safety toggle for rename/delete operations

### Version 1.0.0
- Initial release
- Basic file browsing with List, Tree, and Group views
- Sequence bundling and version detection
- Nuke integration (Read, AudioRead, ReadGeo2 nodes)
- Favorites and history management
- Configuration system
- File preview with OIIO support

---

*Happy compositing with Kadatha!*
