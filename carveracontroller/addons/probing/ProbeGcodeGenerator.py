from carveracontroller.addons.probing.ProbingConstants import ProbingConstants


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