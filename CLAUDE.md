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
