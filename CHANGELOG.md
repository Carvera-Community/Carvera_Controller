[Unreleased]
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