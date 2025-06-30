[unreleased]
- Enhancement: Docker image package. This runs the controller and exposes it over a noVNC web browser, so the controller can be used from multiple locations concurrently
- Change: Clear the WCS rotation if the Gcode file loaded has 4th axis rotation movements
- Change: 4th axis module shape in the preview visualisation in config-and-run screen was for non-harmonic model, now is the correct shape for harmonic version
- Fix: Add 3D Probe tool option to Change/Set if CA1. Previously only added for C1
- Fix: Resolve the keysboard_mode config load error that occurs when reconnecting the Controller after it loses connection
- Fix: Red origin dot in preview visualisation on config-and-run screen returned

[0.9.1]
- Fix: 3D Probe tool number missing a "9". Should be 999990 not 99990
- Fix: Python package builds missing a dep

[0.9.0]
- Enhancement: Initial support for rotated WCS in visualizations
- Enhancement: Controller config option to select what kind of keyboard to use, physical/virtual/both with options for different size virtual
- Enhancement: Default values on the Set Origin screen uses the current origin offsets
- Enhancement: Switch to File view after starting gcode playback
- Enhancement: 3D visualisation for endmill now is transparent and conical to improve visability
- Enhancement: Added Ext Control switch to centre control panel
- Enhancement: Initial Android builds
- Enhancement: Support for Carvera Air specific settings
- Enhancement: Support for the Carvera Air beeper through controller settings
- Change: Minimum Python version increased to 3.9
- Change: Controller no longer warns about missing config key values in MDI because it's assumed that firmware defaults are used instead
- Change: Better wording on the xyz probe screen about block thickness
- Change: Add UI to select X/Y or X/Y/Z WCS zeroing during 3D probing of corners and boss
- Change: 3D Probe is an option in the "Set" Tool menu. This sets the tool to number 99990
- Fix: Compressed gcode now stored in temp directory if source directory isn't writable
- Fix: Fix MDI window showing the keyboard for onscreen keyboard devices on iOS
- Fix: Invisible jog control panel buttons clickable when panel disabled.
- Fix: Movements around the A axis were incorrectly visualised as straight lines between points instead of arcs around the rotational axis

[0.8.2]
- Fix: Linux ARM64 appimage builds
- Change: Minimum Linux X64 appimage build requires running a Linux distribution with Glibc 2.35 or above (eg. Ubuntu 22.04 or higher)
- Fix: Show all .bin files as possible options during firmware upload
- Fix: Fix wrong Z calibration position when running margin command on CA1 when there is high network latency

[0.8.1]
- Fix: Windows Builds in CI

[0.8.0]
- Enhancement: Added 3 axis probing screens for outside/inside corners, single axis, bore/pocket, boxx/block, and angles. Community Firmware V1.0.1c1.0.4_beta or higher is required to use.
- Enhancement: Initial iOS platform support.
- Enhancement: The ability to reduce the size of the autolevel probe area. This enables the ability to avoid probing the stock where there might be obstacles preventing probing.
- Enhancement: tooltip support. Hover mouse cursor for 0.5s for tool tip to popup. See https://github.com/Carvera-Community/Carvera_Controller/pull/143 for more information
- Enhancement: Added custom background images in a dropdown for the start file/probe screen to show bolt hole positions. The user can create custom ones, see release for base image files.
- Enhancement: Set and change to custom tool number (including beyond #6)
- Enhancement: Added enclosure light switch to centre control panel
- Enhancement: Support copy keyboard shortcut from MDI window
- Enhancement: update_translations.py now searches for all .py and .kv files in the project instead of manually adding each one
- Fix: Fixed squished center buttons
- Fix: Fixed Speed/Feed scaling when using +/- buttons. Now can reach 10% and 300% scaling.
- Fix: Fixed firmware download button. Now opens the github releases page for the Community firmware
- Removed: ARM64 (Raspberry Pi etc) version of pre-compiled Linux package. We will be re-added at a later date. For now use the pypi version.

[0.7.1]
- Fix: Set a default for the A axis microsteps per degree config option

[0.7.0]
- Enhancement: Added A axis microsteps per degree config option
- Enhancement: Controller config option to allow MDI usage when machine running
- Change: Add version string to app window title
- Fix: Saved Window size is bigger than actual when DPI scaling is above 1x

[0.6.0]
- Enhancement: add "tool change" as a option for the front button long press actions. This feature requires Community Firmware.
- Enhancement: Support translation file generation, updates, and inclusion into binary. We now can accept translation contributions.
- Change: Using the report bug button opens the controller log directory
- Enhancement: Window size of the app is saved on exit
- Change: Default to showing the Control screen instead of empty file view
- Change: Default window size is now 1440x900
- Enhancement: Controller configuration can now be changed via Settings
- Enhancement: Added configurable Controller UI Density via Settings
- Enhancement: Added configurable screensaver prevention via Settings
- Enhancement: Advanced Jog Controls. Additional controls panel for jogging. Including Ability to set jog movement speed and Keyboard Mode. When keyboard mode is enabled, use Arrow keys for X/Y, and PgUp/PgDown for Z axis movements.
- Fix: "Scan Wi-Fi..." menu option is now non blocking, and will no longer freeze the rest of the UI

[0.5.3]
- Fix: Exception handling for loading machine config file into controller. If the config can't be parsed correctly it will be skipped and a warning message shown on screen.
- Fix: Use correct gcode filename if file was uploaded compressed

[0.5.2]
- Fix: Upload-and-select fails to load local gcode file when machine supports .lz compression

[0.5.1]
- Fix: uploadLocalFile callback causes crash when uploading firmware

[0.5.0]
- Change: Replace Makera logos on icons.
- Change: Improved text on Diagnostics screen
- Change: Allow the use of '*' character in MDI
- Change: Use the command 'diagnose' instead of '*' to poll machine status. This makes the Diagnostics screen cross-compatible with Makera and Community firmware
- Fix: Actually use the Carvera-Community URL for loading this change log
- Enhancement: Confirm before entering laser mode
- Fix: Sliders in Diagnostics screen for Spindle Fan and Vacuum. Used to have broken UX requiring enabling and setting value within 2s. Now enable/disable toggles removed leaving slider to exclusively control value.
- Enhancement: Added Clamp and Unclamp buttons to the Tool Changer drop down
- Enhancement: Added bug report button to menu drop down. Please open github issues for any thing not working correctly.

[0.4.0]
- Fix: A axis rotation in the 3d viewer was incorrect. Previously was CW, not matching the machine since this was changed in FW 0.9.6
- Change: Increase the feed rate scaling range from 50-200 to 10-300. The stepping is still in 10% increments
- Change: Use the Carvera-Community URLs for update checking
- Fix: Show the top of update log on load instead of the bottom
- Change: Renamed the UI button in the local file browser called "Open" to "View" to make it more clear that it's just opening the file for viewing in the controller, not uploading it to the machine.
- Enhancement: Adds a button to the local file browser screen "Upload and Select" which uploads the selected local file and selects it in the controller for playing once uploaded.
- Change: Local file browser defaults to the last directory that had been opened. If the directory doesn't exist, try the next previous etc.

[0.3.1]
- Fix: MacOS dmg background image and icon locations
- Fix: Fix macos build version metadata
- Fix: application name and title to show "Community"

[0.3.0]
- Enhancement: Machine reconnect functionality. Last machine connected manually is now stored in config, and a Reconnect button is added to the status drop down

[0.2.2]
- Fix: Python package version string properly

[0.2.1]
- Fix: Python package version string

[0.2.0]
- Enhancement: Aarch64 and Pypi packages

[0.1.0]
- Enhancement: Linux AppImage packages
- Enhancement: LICENSE and NOTICE files added
- Enhancement: Build scripting and automation via GitHub Actions
- Enhancement: Use temporary directory of OS for file caching
- Enhancement: Bundle package assets into single executable
- Change: Big repo restructure. Code and project files separated, unused files removed, dependency management via Poetry. Updated to latest versions of Kivvy, PyInstaller, pyserial, and Python
- Project start at Makera Controller v0.9.8

[Makera 0.9.8]
1. Optimizing: Improve file transfer speed
2. Optimizing:  wifi Library file upgrade
3. Optimizing: Optimize the file system operation module to improve file read and write speed
4. Optimizing: File transfer adopts compressed file format
5. Optimizing:Improve the stability and reliability of the connection between the machine and the controller
6. Bug fixing:False alarm of soft limit when the machine is powered on
7. Bug fixing:False alarm of hard limit during machine operation
8. Bug fixing: Fix BUG where G0G90/G0G91/G1G90/G1G91 code does not execute
9. Bug fixing: Fixed the bug where the spindle speed occasionally displayed as 0 during the machining process
10. Optimizing:Add the function of "If the probe or tool setter has been triggered before tool calibration, an alarm window will pop up"
11. Optimizing:Add Main Button long press function selection in the configuration page。
12. Optimizing:Modify the automatic dust collection function to be disabled by default, and you can choose whether to enable automatic dust collection on the "Configure and Run" page

[Makera 0.9.7]
Bug Fixing: The laser clustering setting function has been withdrawn due to its potential to cause random crashes. (We will reintroduce this feature once we have resolved the issue and conducted a full test.)

[Makera 0.9.6]
1、Bug fixing：4th axis position is not accurate after large-angle continuous rotation.
2、Bug fixing：4th axis rotation direction is reversed, should follow the right-hand rule (Please check if you manually changed the post processor for the previous false, need to restore that after the upgrade).
3、Bug fixing： Moving wrongly after pause/resume in arc processing.
4、Bug Fixing： The first tool sometimes does not appear in the preview UI panel.
5、Bug Fixing： Incomplete display of the UI in the Android version.
6、Bug Fixing： The Android version cannot access local files.
7、Bug Fixing: Added a laser clustering setting to optimize laser offset issues when engraving at high resolution, particularly with Lightburn software. Note: This feature was withdrawn in version 0.9.7 due to its potential to cause random crashes.
8、Optimizing: Auto leveling, restricting the Z Probe to the 0,0 position from path origin, to ensure leveling accuracy.
9、Optimizing: The software limit switch can now be configured to be on or off, and the limit travel distance can be set.
10、Optimizing: XYZ Probe UI integrated into the Work Origin settings.
11、Optimizing: Adding support for multiple languages (now support English and Chinese).
12、Optimizing: Adding a display for the processing time of the previous task.
13、Optimizing: Input fields in the controller can now be switched with the Tab key.
14、Optimizing: Adding a width-changing feature for the MDI window in the controller.
15、Optimizing: Auto Leveling results can be visually observed on the Z-axis dropdown and a clearing function is provided.
16、Optimizing: Holding the main button for more than 3 seconds allows automatic repetition of the previous task, facilitating the repetitive execution of tasks.

[Makera 0.9.5]
Optimized the WiFi connection file transfer speed and stability.
Added software limit functions to reduce machine resets caused by the false triggering of limit switches.

[Makera 0.9.4]
Added the 'goto' function for resuming a job from a certain line.
Added the WiFi Access Point password setting and enable/disable function.

See the usage at: https://github.com/MakeraInc/CarveraFirmware/releases/tag/v0.9.4

[Makera 0.9.3]
Fixed the WiFi special character bug.
Fixed the identical WiFi SSID display problem.
Fixed the WiFi connectivity unstable problem.
Fixed the spindle stop earlier issue when doing a tool change.

[Makera 0.9.2]
Initial version.

[Makera 0.9.1]
Beta version.
