# DaVinci Resolve DRP Font Auditor & Mapper

A desktop utility tool to audit, scan, and map font family usage across timelines directly from a DaVinci Resolve Project (`.drp`) file—completely offline, without needing to open DaVinci Resolve.

![Dashboard Preview](https://github.com/mrchrisster/davinci-font-auditor/blob/main/media/app.png)

---

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
* Python 3.10 or higher
* A modern web browser

### Running Locally

1. **Clone the repository**:
   ```bash
   git clone https://github.com/chrishelms/Davinci-Font-Mapper.git
   cd Davinci-Font-Mapper
   ```

2. **Start the local backend server**:
   ```bash
   python3 app.py
   ```
   *The server runs on `http://127.0.0.1:5001` with debug reloading enabled.*

3. **Open the Dashboard**:
   Go to your web browser and navigate to:
   **[http://127.0.0.1:5001](http://127.0.0.1:5001)**

4. **Upload a DRP File**:
   * Drag your `.drp` project file into the dashed upload area.
   * View the real-time server logs as it parses the database.
   * Pick a timeline from the dropdown to audit font names, element types (Rich vs Subtitle), and clip timings.

---

## 📄 License

This project is licensed under the MIT License.
