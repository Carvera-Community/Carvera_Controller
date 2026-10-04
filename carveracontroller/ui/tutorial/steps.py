"""Ordered tour script. Plain English; no translation lookup."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TourStep:
    """One spotlight card"""

    step_id: str
    title: str
    body: str
    target_ids: tuple[str, ...]
    screen: str
    icon: str = ""
    popup: str | None = None
    kind: str = "spotlight"


TOUR_STEPS: tuple[TourStep, ...] = (
    TourStep(
        step_id="connect_status",
        title="Status",
        body=(
            "The status button will show you the current state of the machine.\n"
            "You can use it to connect or disconnect from the machine."
        ),
        target_ids=("status_data_view",),
        screen="Control",
        icon="data/status.png",
    ),
    TourStep(
        step_id="position",
        title="Position and work origin",
        body=(
            "Each axis shows its coordinates, both in work coordinate system (the larger numbers) "
            "and in machine coordinate system (the smaller numbers). "
            "You can click on them to override the current work values.\n\n"
            "The button beside them is the active work coordinate system, usually G54. "
            "Other coordinate systems can be configured from the button's menu."
        ),
        target_ids=(
            "x_data_view",
            "y_data_view",
            "z_data_view",
            "a_data_view",
            "coord_system_data_view",
        ),
        screen="Control",
        icon="data/axis-arrow.png",
    ),
    TourStep(
        step_id="feed_and_speed",
        title="Feed and speed",
        body=("Those buttons show you the current feed and spindle speed and allow you to override them."),
        target_ids=("feed_data_view", "spindle_laser_data_view"),
        screen="Control",
        icon="data/spindle.png",
    ),
    TourStep(
        step_id="tool",
        title="Tool selection",
        body=("This button shows you the currently loaded tool. You can change it by clicking on it."),
        target_ids=("tool_data_view",),
        screen="Control",
        icon="data/tool.png",
    ),
    TourStep(
        step_id="jogging",
        title="Jogging",
        body=(
            "The left pad jogs X and Y, and the right pad jogs A and Z.\n\n"
            "The menu in each pad is the step size (i.e. how far the axis will move when you press the button) for those axes."
        ),
        target_ids=("jog_pad", "az_jog_pad"),
        screen="Control",
        icon="data/move.png",
    ),
    TourStep(
        step_id="macros",
        title="Macros",
        body=(
            "These buttons run short G-code macros. You set the name and the commands "
            "for each one in Settings, on the Controller page."
        ),
        target_ids=("macro_bar",),
        screen="Control",
        icon="data/pencil.png",
    ),
    TourStep(
        step_id="actions",
        title="Actions",
        body=(
            "Some actions are available from this group of buttons, such as:\n"
            "- Unlock: Clear an alarm\n"
            "- Reset: Restart the controller\n"
            "- Home: Send the machine home\n"
            "- Margin: Show the outline of the job using the probe's laser\n"
            "- Z probe: Use the probe to set the Z origin\n"
            "- Auto leveling: Setup the auto leveling mesh\n"
            "- Goto: Move the toolhead to a specific position\n"
            "- Set Origin: Set up the current WCS origin\n"
            "- Probing: Open the probing dialog\n\n"
            "You can also access a few tools such as the CMM workbench and the facing "
            'wizard from the "Tools" menu.'
        ),
        target_ids=("manual_actions",),
        screen="Control",
        icon="data/control.png",
    ),
    TourStep(
        step_id="jog_controls",
        title="Jog controls",
        body=(
            "From this group of buttons you can control the current speed and mode "
            "for keyboard jogging or pendant jogging.\n\n"
            "Two modes are available:\n"
            "- Step: One press moves by the step size and stops.\n"
            "- Continuous: The axis keeps moving while you hold the button. This feature is only available when using the Community Firmware.\n\n"
        ),
        target_ids=("jog_controls_bar",),
        screen="Control",
        icon="data/laptop.png",
    ),
    TourStep(
        step_id="run_file_view",
        title="File view",
        body=(
            "The button on the right edge switches between the control view and the file view.\n\n"
            "You can also use the menu button at the top of the window to switch between the two views."
        ),
        target_ids=("screen_toggle",),
        screen="Control",
        icon="data/file.png",
    ),
    TourStep(
        step_id="gcode_mdi",
        title="G-code and MDI",
        body=(
            "This panel shows either the current G-code for the loaded file or the MDI console.\n\n"
            "You can switch between them by clicking on the tab on the top of the panel."
        ),
        target_ids=("gcode_pane",),
        screen="File",
        icon="data/console.png",
    ),
    TourStep(
        step_id="toolpath",
        title="Toolpath preview",
        body=(
            "This is the toolpath of the loaded file that you can control using your mouse or touchscreen.\n\n"
            "You can access the toolbar and widgets by clicking once inside the viewer."
        ),
        target_ids=("gcode_viewer_container", "tool_bar", "gcode_ctl_bar"),
        screen="File",
        icon="data/eye.png",
    ),
    TourStep(
        step_id="select_file",
        title="Select File",
        body=(
            "When you are ready to run a file, you can select it by clicking on this button.\n\n"
            "This will open the file browser where you can choose the file to preview or run."
        ),
        target_ids=("select_file_btn",),
        screen="File",
        icon="data/file.png",
    ),
    TourStep(
        step_id="file_places",
        title="File browser",
        body=(
            "The file browser contains two tabs: one for files on this device and one for files stored on the machine.\n\n"
            'Files that are stored on your device are listed in the "This device" tab and can only be previewed or sent to the machine.\n\n'
            'Those that are stored on the machine are shown in the "CNC Machine" tab and can be previewed, or selected to run.'
        ),
        target_ids=("tab_device", "tab_machine"),
        screen="File",
        icon="data/folder-32.png",
        popup="files",
    ),
    TourStep(
        step_id="file_preview",
        title="Preview without selecting",
        body=(
            "Preview loads a file from this computer into the viewer so you can look "
            "at it before you commit or when you are not connected to the machine.\n\n"
            "It does not copy the file to the machine, and you won't be able to directly run it"
        ),
        target_ids=("file_preview_btn",),
        screen="File",
        icon="data/eye.png",
        popup="files",
    ),
    TourStep(
        step_id="file_play",
        title="Upload and select to play",
        body=(
            "When you are ready to run a file, you can upload it to the machine and select it by clicking on this button.\n\n"
            "This will open the file in the controller for you to review, setup and run."
        ),
        target_ids=("file_upload_select_btn",),
        screen="File",
        icon="data/upload.png",
        popup="files",
    ),
    TourStep(
        step_id="start_file",
        title="Start a job",
        body=(
            "When a file is selected, you can start it by clicking on this button.\n\n"
            "This will open the configuration and run dialog where you can setup the file and ask the machine to run it."
        ),
        target_ids=("start_file_btn",),
        screen="File",
        icon="data/config_start.png",
    ),
    TourStep(
        step_id="config_run",
        title="Config and Run",
        body=(
            "The Config and Run dialog allows you to setup the file before it is run.\n\n"
            "You can choose the work origin, and wether or not features such as scan margin, auto Z probe, and auto leveling should be run before the file."
        ),
        target_ids=("origin_card", "margin_card", "zprobe_card", "leveling_card"),
        screen="File",
        icon="data/cog.png",
        popup="coord",
    ),
    TourStep(
        step_id="job_controls",
        title="Job progress",
        body=(
            "Once a file is running you'll be able to see its progress from the bottom of the screen.\n\n"
            "You'll also be able to pause, stop, or abort the file using those buttons."
        ),
        target_ids=("job_controls_bar",),
        screen="File",
        icon="data/suspend.png",
    ),
    TourStep(
        step_id="menu",
        title="Settings and help",
        body=(
            "This button opens the main menu.\n\n"
            "Settings for this device, language, and the online documentation can be accessed from there."
        ),
        target_ids=("menu_button",),
        screen="Control",
        icon="data/list.png",
    ),
    TourStep(
        step_id="connect_now",
        title="Connect when you are ready",
        body=(
            "Use the status button, or the buttons below, to connect over USB, scan "
            "Wi-Fi, or enter an IP address. You can also close this tour and connect later."
        ),
        target_ids=("status_data_view",),
        screen="Control",
        icon="data/link-variant.png",
        kind="connect",
    ),
)


def tour_steps() -> tuple[TourStep, ...]:
    return TOUR_STEPS
