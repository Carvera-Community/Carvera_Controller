"""CAM-specific G-code header parsers.

Each parser knows how to recognise and extract metadata from the comments a
particular CAM software / post processor writes at the top of a G-code file.
Add new parsers here and register them in
`carveracontroller.addons.cam.extractor.CAM_PARSERS`.

Available parsers:
- fusion360_makera: Fusion 360 Makera post processor tool comments / `(@F360|STOCK|...)` / `ORIGIN`
- makera_studio: Makera Studio `;@MKR|TOOL|...` / `STOCK` / `ORIGIN` metadata block
- freecad_makera: FreeCAD Makera post processor `(@FC|TOOL|...)` / `STOCK` / `ORIGIN` metadata block
"""
