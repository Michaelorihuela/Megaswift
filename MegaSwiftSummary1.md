# MegaSwift — Complete Project Summary

**Last Updated: March 14, 2026**

---

## What is MegaSwift?

MegaSwift is a desktop application for the water utility and civil construction industry. It solves a specific, real-world problem: construction estimators and project managers need to read large PDF plan sets (blueprint drawings) and manually measure distances on those drawings to figure out how much pipe, conduit, or other material is needed — a process called a **takeoff**.

The long-term vision is an AI-assisted or semi-autonomous takeoff tool, meaning Claude (an AI) eventually helps read the drawings and fill in quantities automatically. As of V1.0, the human does the clicking; Claude provides AI fallbacks and a chat assistant embedded in the app.

The closest industry comparison is a commercial product called **PlanSwift** — MegaSwift is a from-scratch Python rebuild of that concept, tailored to water utility work.

---

## Technology Stack

| Layer | Technology | What It Does |
|---|---|---|
| Language | Python 3 | The programming language everything is written in |
| GUI Framework | PyQt6 | Provides windows, buttons, toolbars, drawing canvas, and all user interaction |
| PDF Rendering | PyMuPDF (`fitz`) | Opens PDF files and converts pages into images the app can display |
| AI / Vision | Anthropic Claude API | Powers Auto Scale, Auto Name, and the embedded chat assistant |
| Data Storage | JSON (`.mswift` files) | Saves project state (page names, measurements, scale) to disk |
| Platform | macOS (primary) | Developed on macOS; Windows is a future goal |

**Install all dependencies with:**
```
pip install PyQt6 PyMuPDF anthropic
```

---

## Project File Structure

```
MegaSwift/
├── Megaswift.py              # The entire application — ~1,700 lines, single-file architecture
├── CLAUDE.md                 # Instructions and goals for AI coding assistants
├── MegaSwiftSummary1.md      # This document
└── *.mswift                  # Saved project files (plain JSON, one per project)
```

The single-file approach keeps everything in one place while you're learning and iterating. As projects grow, code is typically split across multiple files (modules), but one file is perfectly valid for a focused tool like this.

---

## Class Architecture — How the Code is Organized

Python organizes code into **classes** — blueprints that bundle related data and behavior together. Each class in MegaSwift has one job. Here is the full hierarchy:

```
Megaswift.py
│
├── ClaudeVisionHelper
│       Renders a PDF region to a PNG image and queries Claude Vision API.
│       Used as a fallback when embedded text extraction finds nothing.
│
├── EndpointHandle  (extends QGraphicsEllipseItem)
│       A small draggable circle at each end of a measurement line.
│       When dragged, it tells its parent MeasurementItem to recalculate.
│
├── MeasurementItem  (extends QGraphicsObject)
│       A complete measurement annotation: two handles + a colored line + a distance label.
│       Draws itself on the PDF canvas and emits a signal when endpoints are moved.
│       Can serialize/deserialize itself to/from a Python dictionary (for saving).
│
├── PageRenderWorker  (extends QObject)
│       Runs on a background thread. Receives a (pdf_path, page_index) request,
│       renders the page via PyMuPDF, and emits the resulting QPixmap back.
│       Exists solely to prevent the UI from freezing during rendering.
│
├── PDFViewer  (extends QGraphicsView)
│       The main PDF canvas. Handles:
│         - Scroll-wheel zoom (cursor-anchored)
│         - Click-drag panning
│         - "Set Scale" two-click mode (orange line)
│         - "Dimension" two-click mode (red lines)
│         - Click to select a measurement, double-click to edit its label
│         - Delete/Backspace key to remove selected measurements
│         - Loading and restoring saved measurements when switching pages
│
├── ProjectPanel  (extends QWidget)
│       The left sidebar. Contains two tabs:
│         - "Pages" tab: a tree showing the project name and all page names
│         - "Takeoff Summary" tab: foldered categories (Drainage, Sewer, Water, etc.)
│       Emits signals when the user selects or double-clicks a page.
│
├── WelcomeScreen  (extends QWidget)
│       The startup screen shown before any project is open.
│       Offers two buttons (new project, open project) and a drag-and-drop PDF target.
│
├── ChatWorker  (extends QObject)
│       Runs on a background thread. Makes a streaming Claude API call and
│       emits each token as it arrives, plus a finished/error signal.
│
├── ChatPanel  (extends QWidget)
│       The collapsible right-side chat panel. Maintains conversation history,
│       sends messages to ChatWorker, and displays Claude's streamed replies live.
│       Automatically injects current page context into Claude's system prompt.
│
└── MainWindow  (extends QMainWindow)
        The top-level window — the "conductor" of the whole application.
        Owns the toolbar, menu bar, and status bar.
        Creates all the other components and connects their signals together.
        Manages project state (_project dict), the render thread, and all
        major user actions (new project, open, save, scale, dimension, auto-name, auto-scale).
```

---

## How the App Starts — Entry Point

At the very bottom of `Megaswift.py`:

```python
def main():
    app = QApplication(sys.argv)     # Start the Qt application runtime
    app.setApplicationName("MegaSwift")
    window = MainWindow()            # Create and configure the main window
    window.show()                    # Make it visible
    sys.exit(app.exec())             # Hand control to Qt's event loop (runs until window closes)

if __name__ == "__main__":
    main()
```

The `if __name__ == "__main__"` guard means this code only runs when you execute the file directly — not if another file imports it. `app.exec()` starts Qt's **event loop**, which sits and waits for user actions (mouse clicks, key presses) and routes them to the right handler functions.

---

## How Data Flows Through the Application

This is the most important thing to understand: how a user action triggers a chain of events across multiple classes.

### Loading a PDF Page

```
User clicks a page in the sidebar
       │
       ▼
ProjectPanel emits  page_selected(index)  signal
       │
       ▼
MainWindow._load_page(index)  receives the signal
  - saves current page measurements back into _project dict
  - emits  _render_requested(pdf_path, page_index)  signal
       │
       ▼
PageRenderWorker.render()  runs on background thread
  - fitz.open(pdf_path) → renders page to QPixmap at 144 DPI
  - emits  page_ready(pixmap, page_index)
       │
       ▼
MainWindow._on_page_ready(pixmap, page_index)  back on main thread
  - calls viewer.load_page(pixmap)  — displays the PDF image
  - calls viewer.load_measurements(saved_data)  — restores annotations
  - updates chat panel context
       │
       ▼
PDFViewer shows the rendered page with all saved measurements drawn on top
```

### Setting the Scale (Manual)

```
User clicks "Set Scale" button
       │
       ▼
MainWindow._start_scale()
  - prompts for known distance in feet (QInputDialog)
  - calls viewer.set_mode(MODE_SCALE, known_distance=feet)
       │
       ▼
PDFViewer is now in MODE_SCALE
  - cursor changes to crosshair
  - first mouse click: records p1
  - second mouse click: records p2, calls _finalize_measurement()
       │
       ▼
PDFViewer._finalize_measurement()
  - calculates pixel distance: math.hypot(dx, dy)
  - feet_per_pixel = known_feet / pixel_distance
  - creates a MeasurementItem (orange, type="scale")
  - emits  scale_set(feet_per_pixel)
       │
       ▼
MainWindow._on_scale_set(feet_per_pixel)
  - stores scale in _project dict
  - updates status bar label: "Scale: 0.013889 ft/px"
```

### Measuring a Distance (Dimension Tool)

```
User clicks "Dimension" button
       │
       ▼
PDFViewer switches to MODE_DIMENSION
  - two mouse clicks record p1 and p2
  - _finalize_measurement() runs
       │
       ▼
distance = pixel_dist * feet_per_pixel
label = "47.23 ft"
MeasurementItem created (red line + label)
       │
       ▼
Both the item and its two EndpointHandles are added to QGraphicsScene
User can drag endpoints to fine-tune — the label updates live
```

### Saving a Project

```
User presses Cmd+S
       │
       ▼
MainWindow._save_project()
  → _write_project(path)
     → _save_current_page_measurements()   (calls viewer.get_measurements())
     → each MeasurementItem.to_dict()      (serializes to plain dict)
     → json.dump(_project, file)           (writes .mswift file to disk)
```

---

## The .mswift Save Format

Project files are plain **JSON** (JavaScript Object Notation) — a human-readable text format for structured data. You can open any `.mswift` file in a text editor to see exactly what is saved.

```json
{
  "name": "Downtown Water Main Replacement",
  "pdf_path": "/Users/you/Projects/plans.pdf",
  "scale_feet_per_pixel": 0.013889,
  "pages": [
    {
      "name": "C-1",
      "index": 0,
      "measurements": [
        {
          "type": "scale",
          "p1": [120.0, 880.0],
          "p2": [840.0, 880.0],
          "label": "Scale: 100.00 ft",
          "color": "#ff8800",
          "known_feet": 100.0
        },
        {
          "type": "dimension",
          "p1": [200.0, 400.0],
          "p2": [650.0, 400.0],
          "label": "62.47 ft",
          "color": "#ff3232"
        }
      ]
    },
    {
      "name": "C-2",
      "index": 1,
      "measurements": []
    }
  ]
}
```

The `.mswift` extension is custom — it is just a `.json` file with a different name to make it easier to associate with MegaSwift in the file system.

---

## AI Features — How Claude is Used

### Auto Scale

When you click **Auto Scale**, the app tries two strategies in sequence:

1. **Text extraction (fast, free):** PyMuPDF reads the embedded text from the bottom 25% of the page (where civil drawing title blocks live). A regex pattern searches for expressions like `1" = 20'` or `1:240`. If found, the scale is applied immediately.

2. **Claude Vision fallback (for scanned PDFs):** If no text is found (e.g., the PDF is a scanned image with no embedded text), the same title block region is rendered to a PNG and sent to Claude with the prompt: *"What is the drawing scale? Reply with ONLY the scale expression."* Claude's answer is run through the same regex parser.

### Auto Name Pages

Same two-step strategy, applied to every page:
1. Read the bottom-right 5% corner for embedded text (sheet numbers live there: "C-1", "W-3", "Sheet 1 of 12").
2. If no text, send a slightly wider crop to Claude Vision: *"What is the sheet number or sheet name? Reply with ONLY the sheet identifier."*

### Claude Chat Panel

The right-side chat panel is a full multi-turn conversation interface. Every message includes a **system prompt** that tells Claude its role and context:

```
"You are an expert civil engineering plan reviewer embedded inside MegaSwift,
a water utility takeoff application. Answer questions concisely...

Current page context: Project: Downtown Main | Page 3 of 12: 'C-3' | Scale: 0.013889 ft/px"
```

Responses are **streamed** — tokens arrive one at a time and are inserted into the display as they come, rather than waiting for the full response. This uses a **background QThread** so the UI never freezes during an API call.

---

## Key Coding Concepts Explained

### Object-Oriented Programming (OOP)

The entire application is built using OOP. Every major piece of the UI is a **class**. A class is like a template or blueprint:

```python
class MeasurementItem(QGraphicsObject):    # blueprint definition
    def __init__(self, p1, p2, label, color, mtype):   # constructor — called when you create one
        self._p1 = p1       # instance variable — belongs to THIS specific measurement
        self._label = label

    def set_label(self, text):   # method — an action this object can perform
        self._label = text
        self.update()            # tell Qt to redraw this item
```

You create an **instance** (a real object from the blueprint) like this:
```python
item = MeasurementItem(p1, p2, "47.23 ft", QColor("#ff3232"), "dimension")
```

### Inheritance

Classes can **extend** other classes, inheriting all their capabilities:

```python
class PDFViewer(QGraphicsView):   # PDFViewer IS a QGraphicsView, plus our custom code
```

`QGraphicsView` already knows how to display a scene, handle scroll events, and manage zoom — `PDFViewer` inherits all of that, and we only add or override the specific behavior we want (mouse click handling, our zoom limits, etc.).

### Qt Signals and Slots — How Components Communicate

Qt's signal/slot system is the most important pattern to understand. Instead of one class calling another class's methods directly (which creates tight coupling), components **broadcast events** via signals, and other components **listen** via slots.

```python
# In PDFViewer — declares a signal
scale_set = pyqtSignal(float)   # will carry a float value when emitted

# In PDFViewer — emitting the signal
self.scale_set.emit(self._feet_per_pixel)   # "something happened — here's the value"

# In MainWindow — connecting the signal to a handler (slot)
self.viewer.scale_set.connect(self._on_scale_set)

# In MainWindow — the slot (just a normal method)
def _on_scale_set(self, feet_per_pixel: float):
    self.scale_label.setText(f"Scale: {feet_per_pixel:.6f} ft/px")
```

`PDFViewer` doesn't know anything about `MainWindow`. It just says "the scale was set." `MainWindow` decides what to do with that information. This **decoupling** makes code much easier to change and test.

### Threads — Keeping the UI Responsive

A desktop app has one **main thread** that handles all user interaction and drawing. If you do something slow on the main thread (reading a large PDF, making an API call), the entire UI freezes.

The solution: move slow work to a **background thread**.

```python
class PageRenderWorker(QObject):       # the worker
    page_ready = pyqtSignal(QPixmap, int)   # signal to send result back

    @pyqtSlot(str, int)
    def render(self, pdf_path, page_index):
        # This runs on the background thread
        doc = fitz.open(pdf_path)
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(2, 2))
        pixmap = QPixmap.fromImage(...)
        self.page_ready.emit(pixmap, page_index)   # sends result back to main thread

# In MainWindow — setting it up
self._render_thread = QThread()
self._render_worker = PageRenderWorker()
self._render_worker.moveToThread(self._render_thread)   # move worker to background thread
self._render_requested.connect(self._render_worker.render)   # connect trigger signal
self._render_worker.page_ready.connect(self._on_page_ready)  # connect result signal
self._render_thread.start()
```

Qt's signal/slot system is **thread-safe** — it knows how to route signals across thread boundaries correctly.

### Serialization — Saving Objects to Disk

**Serialization** means converting an in-memory object into a format that can be written to disk (and later read back). MegaSwift uses JSON for this.

```python
# MeasurementItem knows how to save itself
def to_dict(self) -> dict:
    return {
        "type": self._mtype,
        "p1": [self._p1.x(), self._p1.y()],
        "p2": [self._p2.x(), self._p2.y()],
        "label": self._label,
        "color": self._color.name(),
    }

# And how to restore itself from a saved dict
@staticmethod
def from_dict(d: dict) -> "MeasurementItem":
    p1 = QPointF(d["p1"][0], d["p1"][1])
    p2 = QPointF(d["p2"][0], d["p2"][1])
    return MeasurementItem(p1, p2, d["label"], QColor(d["color"]), d["type"])
```

This pattern — `to_dict()` / `from_dict()` — is extremely common in application development.

### Regular Expressions (Regex)

Regex is a mini-language for pattern matching inside strings. MegaSwift uses it to find scale expressions in PDF text:

```python
# Finds: 1" = 20'  or  1"=40'  or  SCALE: 1" = 30'
m = re.search(
    r'1\s*["\u201c\u201d\u2033]\s*=\s*(\d+(?:\.\d+)?)\s*[\'\u2018\u2019\u2032]',
    text
)
```

Breaking that pattern down:
- `1` — literal character "1"
- `\s*` — zero or more spaces
- `["\u201c\u201d\u2033]` — any of: straight quote, left curly quote, right curly quote, double prime
- `\s*=\s*` — equals sign surrounded by optional spaces
- `(\d+(?:\.\d+)?)` — one or more digits, optionally followed by a decimal point and more digits — this is **captured** (the parentheses save it)
- `[\'\u2018\u2019\u2032]` — any foot/apostrophe character

### Optional Dependencies and Graceful Degradation

MegaSwift works without the Claude API installed. It achieves this with a try/except import guard and a global flag:

```python
try:
    import anthropic as _anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
```

Every AI feature checks this flag before proceeding:
```python
if not ANTHROPIC_AVAILABLE:
    self.status.showMessage("Install 'anthropic' for AI fallback.")
    return
```

This is called **graceful degradation** — the app loses a feature but never crashes.

---

## The QGraphicsScene / QGraphicsView System

This is Qt's most powerful drawing system and the heart of the PDF viewer. Understanding it is key to understanding PDFViewer.

```
QGraphicsScene  =  The "world"
                   - Has no concept of pixels or screen position
                   - Contains items: pixmaps, lines, shapes, custom objects
                   - Items have positions in "scene coordinates"

QGraphicsView   =  The "camera" looking into the world
                   - Has a transform (pan + zoom)
                   - Renders what the camera can see onto the screen
                   - Mouse events arrive in "viewport coordinates" (pixels on screen)
                   - mapToScene() converts viewport coordinates to scene coordinates
```

When the user zooms in, only the **view's transform** changes — the scene and its items stay exactly the same. This is why `pen.setCosmetic(True)` is important: a cosmetic pen stays 2 pixels wide on screen regardless of zoom, instead of zooming with the scene.

```
Scene coordinates = PDF points × render scale factor (2.0)
Screen coordinates = Scene coordinates × view transform
```

---

## Architecture Patterns Used

### 1. QThread + Worker Pattern
For any operation that could freeze the UI (PDF rendering, API calls), a `QObject` worker is created and moved to a `QThread`. Results come back via signals. Used for `PageRenderWorker` and `ChatWorker`.

### 2. Stacked Widget Pattern
`QStackedWidget` shows one screen at a time. Index 0 = WelcomeScreen, Index 1 = workspace. Switching is a single line: `self.stack.setCurrentIndex(1)`.

### 3. Single Source of Truth
`MainWindow._project` is the one canonical dictionary that holds all project state. All components read from or write to it through `MainWindow`. No other class owns project data.

### 4. Signal/Slot Decoupling
Components never hold references to each other (except where `MainWindow` wires them together). They communicate through signals. This means you could swap out `ProjectPanel` for a completely different sidebar widget without touching `PDFViewer`.

### 5. Two-Strategy Fallback (Text then Vision)
Both Auto Scale and Auto Name try the fast, free, offline path first (embedded PDF text extraction). They only call the Claude API if that fails. This keeps costs low and the app fast for standard PDFs.

---

## What V1 Can Do (Feature Checklist)

- [x] Open large PDF files
- [x] Organize pages under a user-named project
- [x] Automatically extract page names from PDF bookmarks and page labels
- [x] Rename pages manually (toolbar button or double-click in sidebar)
- [x] Zoom in/out with mouse scroll wheel (cursor-anchored)
- [x] Click-drag to pan
- [x] Set scale using a two-click reference line
- [x] Measure distances using a two-click dimension line
- [x] Measurement lines persist on screen with distance labels
- [x] Drag endpoints to fine-tune scale and dimension lines
- [x] Click to select a measurement, Delete key to remove it
- [x] Double-click a measurement to edit its label
- [x] Save/load projects to `.mswift` files
- [x] Auto Name Pages using embedded text + Claude Vision fallback
- [x] Auto Scale using embedded text + Claude Vision fallback
- [x] Embedded Claude chat panel with page context and streaming responses
- [x] API key management saved to `~/.megaswift_config.json`
- [x] Background thread rendering (UI stays responsive during page loads)
- [x] Drag-and-drop PDF loading from the welcome screen
- [x] Takeoff Summary tab in the sidebar (categories: Drainage, Sewer, Water, etc.)

---

## Roadmap — What Comes Next

### V1.x (Near Term)
- **Tiled/on-demand rendering** — only render the visible viewport portion at the current zoom, instead of the full page at once. Dramatically improves performance for large 36"x48" plan sheets.
- **Quantity tallying** — let the user assign measurements to Takeoff Summary categories and sum them up.
- **Export** — CSV or PDF report of all measurements.

### V2 (AI-Driven)
- Claude reads a page and automatically identifies pipe runs, notes their size and material, and suggests where to draw dimension lines.
- Semi-autonomous takeoff: Claude does an initial pass, the human reviews and corrects.
- AI-generated quote estimates based on material quantities and unit prices.

---

## Glossary — Domain Terms

| Term | Definition |
|---|---|
| **Takeoff** | The process of reading construction drawings and counting/measuring all the materials needed |
| **Plan set** | A set of construction drawings packaged as a PDF, typically dozens to hundreds of pages |
| **Title block** | The standardized information box printed at the bottom (or side) of every drawing page; contains sheet number, scale, date, project name |
| **Sheet number** | The identifier for a single drawing page, e.g. "C-1" (Civil sheet 1), "W-3" (Water sheet 3) |
| **Scale** | The ratio between drawing size and real-world size, e.g. 1" = 20' means 1 inch on paper = 20 feet in the field |
| **Feet per pixel** | MegaSwift's internal scale unit — how many real-world feet one screen pixel represents at the render resolution |
| **Force main** | A pressurized water or sewer pipe (pumped, not gravity-fed) |
| **Civil plan** | A drawing showing site work: roads, grading, drainage, utilities |
