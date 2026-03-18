# MegaSwift Project

## Overview
A water utility civil plan takeoff application built in Python, inspired by Planswift.
The long-term goal is an AI-powered takeoff tool capable of semi-autonomous takeoffs and quotes.

## Language & Stack
- Language: Python 3
- Primary file: MegaSwift.py
- GUI Framework: PyQt6
- PDF Rendering: PyMuPDF (fitz)
- Run the script after making changes to verify it works
- Platform: macOS (Windows compatibility is a future goal)

## Dependencies (must be installed before running)
    pip install PyQt6 PyMuPDF

## V1 Goals (Planswift Feature Parity)
1. Open large PDF files
2. Organize pages under a named project (user-defined)
3. Break PDFs into individual pages that can be renamed
4. Zoom in/out via mouse scroll wheel
5. Scale pages using a two-click line tool (user enters known footage)
6. Dimension tool to verify scale with a two-click measurement line

## Project File Format
- Extension: .mswift
- Format: JSON
- Stores: project name, PDF path, page names, scale factor

## Scale Tool Workflow
1. User clicks "Set Scale" button
2. Dialog prompts for known distance in feet
3. User clicks start point on PDF, then end point
4. App calculates and stores feet-per-pixel ratio

## Dimension Tool Workflow
1. User clicks "Dimension" button (requires scale to be set)
2. User clicks start and end points on PDF
3. App displays calculated real-world distance in feet

## AI / Ollama Integration
- Chat panel (right sidebar) uses `llama3.2` by default for text conversation
- Vision model (`llava`) is used for Auto Name and Auto Scale fallback on image-only PDFs
- **Chat panel is wired to llava vision** ✓ — when a page is loaded, the current page is rendered to PNG (2x / 144 DPI) and attached to every user message; the chat routes to `_ollama_vision_model` (llava) automatically, so the model sees exactly what the user sees
- Model label in chat panel updates to show "Model: llava (vision)" when a page is active
- All three Ollama settings (chat model, vision model, host URL) are persisted to `~/.megaswift_config.json`
- Configurable via File → Ollama Settings…

## Future Work (V1.x)
- Measurement lines persist after use (scale + dimension lines stay on screen) ✓
- Labels showing measured distance displayed just above each line ✓
- Measurements are selectable and editable (click to select, edit distance or delete) ✓
- Background thread rendering — page loads should not freeze the UI; render on a worker thread so the interface stays responsive during page switches (addresses performance gap vs Planswift) ✓
- Tiled/on-demand rendering — only render the visible portion of the page at the current zoom level, rather than the full page at once; significant improvement for large plan sheets

## Domain Context
- Industry: Water utility / civil construction
- Use case: Reading construction plan sets (PDFs) and performing material takeoffs
- End goal: AI-assisted or semi-autonomous takeoffs and quoting
