# DaVinci Resolve DRP Font Auditor & Mapper

A desktop utility tool to audit, scan, and map font family usage across timelines directly from a DaVinci Resolve Project (`.drp`) file—completely offline, without needing to open DaVinci Resolve.

![Dashboard Preview](https://github.com/mrchrisster/davinci-font-auditor/blob/main/media/app.png)

---
## What you might need it for

I developed this tool because transferring a project between Windows and Mac revealed that not all fonts were named the same between Windows and Mac. Instead of manually going through the project and updating all fonts, you can use this tool to update text slates with different fonts.

This is also very useful to check if all fonts in your project are consistent or if some text slates have the wrong font installed.
  
  
## 🚀 Key Features

* **DRP Container Extraction**: Instantly ingests and extracts `.drp` files.
* **Automatic Timeline Mapping**: Scans the Media Pool database structure to map friendly timeline names to their underlying sequence XML files.
* **Deep Font Auditing**:
  * **Subtitles**: Parses HTML-like styling markup from subtitle generator tracks.
  * **Rich Text / Fusion Titles**: Decompresses binary properties 
* **Dynamic Font Face Detection**
* **Specificity Deduplication**: Resolves font name substrings to prevent duplicate cards (e.g., matching `"Helvetica Neue LT Std"` and ignoring the redundant `"Helvetica"` and `"Helvetica Neue"`).
* **Title Content Extraction**
* **Sleek Dark Suite Web UI**

---

## 📦 Installation & Setup

### Prerequisites
* Python 3.10 or higher (ensure Python is added to your PATH/environment variables during installation)
* A modern web browser

### 🚀 Easy Launch (Recommended)

1. **Clone or Download the repository**:
   - Clone via Git: `git clone https://github.com/chrishelms/Davinci-Font-Mapper.git`
   - Or click **Code -> Download ZIP** on GitHub and unzip the folder.
2. **Run the launcher**:
   - **macOS**: Double-click `run_mac.command` in the project folder.
     *Note: If macOS displays a security warning, right-click the file, choose **Open**, and click **Open** in the dialog.*
   - **Windows**: Double-click `run_windows.bat` in the project folder.

*The script will automatically install/update dependencies, launch the local backend server, and open your browser to your new dashboard at **[http://127.0.0.1:5001](http://127.0.0.1:5001)**.*

---

### 💻 Manual Launch

If you prefer running the application from the command line:

1. **Navigate to the project folder**:
   ```bash
   cd Davinci-Font-Mapper
   ```

2. **Install dependencies**:
   ```bash
   python3 -m pip install -r requirements.txt
   ```

3. **Start the local server**:
   ```bash
   python3 app.py
   ```

4. **Open the Dashboard**:
   Open your browser and navigate to **[http://127.0.0.1:5001](http://127.0.0.1:5001)**.

5. **Upload a DRP File**:
   * Drag your `.drp` project file into the dashed upload area.
   * View the real-time server logs as it parses the database.
   * Pick a timeline from the dropdown to audit font names, element types (Rich vs Subtitle), and clip timings.

---

## 📄 License

This project is licensed under the MIT License.
