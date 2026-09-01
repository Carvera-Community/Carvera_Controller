# Play-file background images

These images are shown behind the toolpath preview on the Config and Run screen. The Controller stretches the PNG to fill the workspace widget, so the photo must be cropped and scaled to the machine **work area**, not the full physical bed.

## How alignment works

- The widget aspect ratio is `worksize_y / worksize_x` from the machine config (C1 ≈ 240/340, CA1 = 200/300, Z1 = 200/200).
- Bottom-left of the image is the **outer** corner of the L-bracket (workspace origin).
- Anchor1 at 0,0 is drawn at `(anchor_width, anchor_width)` — 15 mm in from that corner, at the inner "pit" of the L.
- Crop from the southwest (bottom-left) so that origin stays pinned to the L. Hand-tune until the blue origin marker sits in the pit.

You'll need [ImageMagick](https://imagemagick.org/). Fusion 360 is only required when capturing a new screenshot from a 3D model.

## Z1 bed

Source: `Z1_source.png` (2170×2170 px screenshot of the 205×205 mm bed, L-bracket flush with the bottom-left).

The Z1 work area is 200×200 mm. The L inner pit in the source is at x=161, 162 px from the bottom. Inset 15 mm from that pit to get the outer corner, then crop 200 mm square and resize:

```
# 2170 px = 205 mm; pit at (161, 162 from bottom); 15 mm inset; 200 mm work area
magick Z1_source.png -gravity SouthWest \
  -crop 2117.073x2117.073+2.220+3.220 +repage -resize 2048x2048 \
  ../../../carveracontroller/data/play_file_image_backgrounds/Z1.png
```

If you recapture the bed, measure the inner pit in the new image and recompute:

```
px_per_mm = image_width / 205
origin_x = pit_x - 15 * px_per_mm
origin_y_from_bottom = pit_y_from_bottom - 15 * px_per_mm
crop = 200 * px_per_mm
```

Then `-crop ${crop}x${crop}+${origin_x}+${origin_y_from_bottom}` with `-gravity SouthWest`.

## CA1 SMW fixture plates

Download the .step files from [SMW's site](https://saundersmachineworks.com/products/makera-carvera-air-fixture-tooling-plate?variant=49754761756969) and load them into Fusion. Then export the L-bracket from [Carvera-3 Axis_MachineModel v9](https://github.com/Carvera-Community/Carvera_Community_Profiles/blob/2c02047d8d62e46d2d76039b01e511244c214934/Machine_Design_Files/Carvera-3%20Axis_MachineModel%20v9.step) in the community profiles repo, import it into Fusion, and add it as a component in the model (I used the Data Panel for this).

To make the Fusion model look similar to the existing background images, edit the Display Settings (bottom tool panel):

- Visual style -> Wire frame with visible edges only
- Environment -> Dark sky

Then, zoom in on the model in Fusion as much as possible while keeping the entire bed in view, let the mouse hover over the bed so that it's highlighted in gray, and take a screenshot. Crop the image to the edges and corners of the bed using your screenshot program or a separate image editor. Save the images as `CA1_SMW_Metric.png` and `CA1_SMW_Inch.png`.

You may need to hand-tune the percentages in the `-crop` command until the image alignment seems correct in the Controller UI.

### Metric

```
# Resize to full width
magick CA1_SMW_Metric.png -resize 2048x CA1_SMW_Metric_resized_to_width.png

# Crop to fit the Controller work area (keep bottom-left / L-bracket)
magick CA1_SMW_Metric_resized_to_width.png -gravity SouthWest -crop 98.15%x95.25%+0+0 +repage CA1_SMW_Metric_cropped.png

# Copy into place
cp CA1_SMW_Metric_cropped.png ../../../carveracontroller/data/play_file_image_backgrounds/CA1\ SMW\ Metric.png
```

### Inch

```
# Resize to full width
magick CA1_SMW_Inch.png -resize 2048x CA1_SMW_Inch_resized_to_width.png

# Crop to fit the Controller work area (keep bottom-left / L-bracket)
magick CA1_SMW_Inch_resized_to_width.png -gravity SouthWest -crop 98.25%x94.90%+0+0 +repage CA1_SMW_Inch_cropped.png

# Copy into place
cp CA1_SMW_Inch_cropped.png ../../../carveracontroller/data/play_file_image_backgrounds/CA1\ SMW\ Inch.png
```
