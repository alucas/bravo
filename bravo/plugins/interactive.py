from zope.interface import implements

from bravo.blocks import blocks
from bravo.ibravo import IInteractiveHook
from bravo.inventory import sync_inventories, Workbench
from bravo.packets.beta import make_packet

class InteractiveWorkbench(object):
    """
    """

    implements(IInteractiveHook)

    def interactive_hook(self, factory, protocol, player, block):
        if block == blocks["workbench"].slot:
            i = Workbench()
            sync_inventories(player.inventory, i)
            protocol.windows[protocol.wid] = i
            packet = make_packet("window-open", wid=protocol.wid, type="workbench",
                title="Hurp", slots=2)
            protocol.wid += 1
            protocol.transport.write(packet)

            return False

        return True

    name = "workbench"

    before = tuple()
    after = tuple()

workbench = InteractiveWorkbench()