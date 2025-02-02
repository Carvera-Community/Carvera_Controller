from abc import abstractmethod, ABC
from enum import Enum
from kivy.properties import StringProperty, BooleanProperty

from carveracontroller.addons.probing.ProbingConstants import ProbingConstants


# Docs: https://github.com/Carvera-Community/Carvera_Community_Firmware/blob/master/tests/TEST_ProbingM460toM465/TEST_ProbingM460toM465_readme.txt

class M464Params:
    # X distance along the particular axis to probe.
    XAxisDistance = "X",

    # Y distance along the particular axis to probe.
    YAxisDistance = 'Y',

    # H: Optional parameter, if set the probe will probe down by this value to find the
    # pocket bottom and then retract slightly before probing the sides of the bore.
    # Useful for shallow pockets
    PocketProbeDepth = 'H',

    # F: optional fast feed rate override
    FastFeedRate = 'F',

    # K: optional rapid feed rate override
    RapidFeedRate = 'K',

    # L: setting L to 1 will repeat the entire probing operation from the newly found centerpoint
    RepeatOperationCount = 'L',

    # R: changes the retract distance from the edge of the pocket for the double tap probing
    EdgeRetractDistance = 'R',

    # C: optional parameter, if H is enabled and the probe happens, this is how far to retract off the bottom surface of the part. Defaults to 2mm
    BottomSurfaceRetract = 'C',

    # S: save corner position as new WCS Zero in X and Y
    ZeroXYPosition = 'S',

    # D: Probe Tip Diameter, stored in config
    ProbeTipDiameter = 'D',

    # E: how far below the top surface of the model to move down in order to probe on each side. D uses an
    # optional probe routine, so if it hits a surface it will slightly retract before probing the x or y axis.
    ProbeDepth = 'E',

    # Specify 1 for a Probe that is normally closed, otherwise
    UseProbeNormallyClosed = 'I'


class BaseOperation(ABC):
    @abstractmethod
    def generate(self, config: dict[str, float]) -> str:
        pass

    def config_to_gcode(self, config: dict[str, float]) -> str:
        return ' '.join([f'{key}={value}' for key, value in config.items()])


class OutsideCornerOperation(BaseOperation):
    def __init__(self, title, code, fromRight: BooleanProperty, fromBottom, **kwargs):
        self.title = title
        self.code = code
        self.fromRight = fromRight
        self.fromBottom = fromBottom

    def generate(self, config: dict[str, float]):

        if M464Params.XAxisDistance in config and self.fromRight:
            config[M464Params.XAxisDistance] = config[M464Params.XAxisDistance] * -1

        if M464Params.YAxisDistance in config and self.fromBottom:
            config[M464Params.YAxisDistance] = config[M464Params.YAxisDistance] * -1

        return self.code + self.config_to_gcode(config)


class ProbeGcodeGenerator():
    @staticmethod
    def get_straight_probe(x, y, z, a, switch_type):
        if switch_type == ProbingConstants.switch_type_nc:
            command = "G38.4"
        else:
            command = "G38.2"

        suffix = ""
        if len(x) > 0:
            suffix += f" X{x}"
        if len(y) > 0:
            suffix += f" Y{y}"
        if len(z) > 0:
            suffix += f" Z{z}"
        if len(a) > 0:
            suffix += f" A{a}"

        if len(suffix) > 0:
            return command + suffix

        return ""

class ProbeOperation(Enum):
    OutsideCornerTopLeft = OutsideCornerOperation("Top Left", "M464", False, False)
    # OutsideCornerTopRight = OutsideCornerOperation("Top Right", "M464", fromRight=True, fromBottom=False)
    # OutsideCornerBottomRight = OutsideCornerOperation("Bottom Right", "M464", fromRight=True, fromBottom=True)
    # OutsideCornerBottomLeft = OutsideCornerOperation("Bottom Left", "M464", fromRight=False, fromBottom=False)

