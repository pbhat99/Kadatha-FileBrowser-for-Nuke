# Kadatha - Nuke File Browser

## Overview
Kadatha is a file browser plugin for **Nuke** designed to streamline asset management. It allows users to scan specific directories,search files and manage assets efficiently.

---

## Features
- ✅ File scanning with customizable filters
- ✅ power full search and highlight 
- ✅ Folder management with version tracking
- ✅ Favorites and history management
- ✅ Customizable settings (extensions, depth, etc.)

---

## Requirements
- **Nuke 16+**

---

## Installation Guide

### 1. Prerequisites
- Ensure **Nuke** is installed (version 15 or higher).

### 2. Download and instal Kadatha
- Download from [repository link] and place the `kadatha` in nuke path 
- add folder path in init.py
- Restart Nuke. 

### 3. First Use
- Launch Kadatha via `File > viewer > Kadatha`.
- It will launch panel

---

## Configuration

### 1. File Extensions
- **What to do**: Specify file types to scan (e.g., `.mov`, `.png` `.abc`).
- **How**: In Kadacha's `Config` dialog, enter extensions in the `Extensions` field.

### 2. Ignore Directories
- **What to do**: Skip unwanted folders (e.g., `.git`).
- **How**: Add file and folder names to the `Ignore List`.

### 3. Search Depth
- **What to do**: Control how deep Kadacha explores subfolders.
- **How**: Adjust the `Max Depth` slider (0 = current folder only).

### 4. File mutations
- Enable delete and rename if required
- It shows in right click context menu


---

## Usage

### 1. Scanning a Directory
1. Set the path in the top bar.
2. Click `Refresh` to start scanning.

### 2. Preview Files
- Hover over a file in the list to see a preview (if supported).

### 3. Favorites
- Add paths to favorites for quick access.

---

## Credits
- **Prasannakumar T Bhat**: Developed Kadatha for Nuke.
- **Sam Richards**: Original concept and file scaner foundation.

---

## License
Apache License 2.0  
Copyright (c) 2026 Prasannakumar T Bhat

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.