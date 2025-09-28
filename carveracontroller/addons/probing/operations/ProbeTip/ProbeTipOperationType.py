from enum import Enum
from carveracontroller.addons.probing.operations.ProbeTip.ProbeTipOperation import ProbeTipOperationBore
from carveracontroller.addons.probing.operations.ProbeTip.ProbeTipOperation import ProbeTipOperationBoss
from carveracontroller.addons.probing.operations.ProbeTip.ProbeTipOperation import ProbeTipOperationAnchor


class ProbeTipOperationType(Enum):
    Bore = ProbeTipOperationBore("Bore", True, False,False, "")
    BossX = ProbeTipOperationBoss("BossX", True, False,False, "")
    BossY = ProbeTipOperationBoss("BossY", False, True,False, "")
    Anchor2 = ProbeTipOperationAnchor("Anchor2", False, False,False, "")
