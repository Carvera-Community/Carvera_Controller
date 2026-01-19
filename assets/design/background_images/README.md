# Generating SMW fixture plate images

To generate these images, you'll need Fusion 360 and ImageMagick installed.

## Set up the Fusion model and take screenshots

Download the .step files from [SMW's site](https://saundersmachineworks.com/products/makera-carvera-air-fixture-tooling-plate?variant=49754761756969) and load them into Fusion. Then export the L-bracket from [Carvera-3 Axis_MachineModel v9](https://github.com/Carvera-Community/Carvera_Community_Profiles/blob/2c02047d8d62e46d2d76039b01e511244c214934/Machine_Design_Files/Carvera-3%20Axis_MachineModel%20v9.step) in the community profiles repo, import it into Fusion, and add it as a component in the model (I used the Data Panel for this).

To make the Fusion model look similar to the existing background images, edit the Display Settings (bottom tool panel):
- Visual style -> Wire frame with visible edges only
- Environment -> Dark sky

Then, zoom in on the model in Fusion as much as possible while keeping the entire bed in view, let the mouse hover over the bed so that it's highlighted in gray, and take a screenshot. Crop the image to the edges and corners of the bed using your screenshot program or a separate image editor. Save the images as `CA1_SMW_Metric.png` and `CA1_SMW_Inch.png`.

We'll use the [ImageMagick](https://imagemagick.org/) command line tool to manipulate the screenshots in the following steps. Any similar image editor could be used instead. You may need to hand-tune the percentages in the `-crop` command until the image alignment seems correct in the Controller UI.

## Resize, crop, and copy into place

### Metric

```
# Resize to full width
magick CA1_SMW_Metric.png -resize 2048x CA1_SMW_Metric_resized_to_width.png

# Crop to fit fixed dimensions and aspect ratio in the Controller
magick CA1_SMW_Metric_resized_to_width.png -gravity SouthWest -crop 98.15%x95.25%+0+0 +repage CA1_SMW_Metric_cropped.png

# Copy into place
cp CA1_SMW_Metric_cropped.png ../../../carveracontroller/data/play_file_image_backgrounds/CA1\ SMW\ Metric.png
```

### Inch

```
# Resize to full width
magick CA1_SMW_Inch.png -resize 2048x CA1_SMW_Inch_resized_to_width.png

# Crop to fit fixed dimensions and aspect ratio in the Controller
magick CA1_SMW_Inch_resized_to_width.png -gravity SouthWest -crop 98.25%x94.90%+0+0 +repage CA1_SMW_Inch_cropped.png

# Copy into place
cp CA1_SMW_Inch_cropped.png ../../../carveracontroller/data/play_file_image_backgrounds/CA1\ SMW\ Inch.png
```
