import collections
import itertools

from twisted.internet.protocol import Protocol
from twisted.internet.task import coiterate, LoopingCall

from construct import Container

from beta.alpha import Player
from beta.blocks import blocks
from beta.packets import parse_packets, make_packet, make_error_packet
from beta.utilities import split_coords

(STATE_UNAUTHENTICATED, STATE_CHALLENGED, STATE_AUTHENTICATED) = range(3)

class AlphaProtocol(Protocol):
    """
    The Minecraft Alpha protocol.
    """

    excess = ""
    packet = None

    state = STATE_UNAUTHENTICATED

    buf = ""
    parser = None
    handler = None

    def __init__(self):
        print "Client connected!"

        self.chunks = dict()
        self.chunk_lfu = collections.defaultdict(int)

        self.handlers = collections.defaultdict(lambda: self.unhandled)
        self.handlers.update({
            0: self.ping,
            3: self.chat,
            5: self.inventory,
            10: self.flying,
            11: self.position_look,
            12: self.position_look,
            13: self.position_look,
            14: self.digging,
            15: self.build,
            16: self.equip,
            255: self.quit,
        })

    def ping(self, container):
        pass

    def chat(self, container):
        message = container.message

        print "--- %s" % message

        packet = make_packet("chat", message=message)

        self.factory.broadcast(packet)

    def inventory(self, container):
        if container.unknown1 == -1:
            self.player.inventory.load_from_packet(container)
        elif container.unknown1 == -2:
            self.player.crafting.load_from_packet(container)
        elif container.unknown1 == -3:
            self.player.armor.load_from_packet(container)

    def flying(self, container):
        self.player.location.load_from_packet(container)

    def position_look(self, container):
        oldx, chaff, oldz, chaff = split_coords(self.player.location.x,
            self.player.location.z)

        self.player.location.load_from_packet(container)

        pos = (self.player.location.x, self.player.location.y,
            self.player.location.z)

        x, chaff, z, chaff = split_coords(pos[0], pos[2])

        if oldx != x or oldz != z:
            self.update_chunks()

        for entity in self.factory.entities_near(pos[0] * 32,
            self.player.location.y * 32, pos[2] * 32, 64):

            packet = make_packet("pickup", type=entity.entity_type, quantity=1, wear=0)
            self.transport.write(packet)

            packet = make_packet("destroy", id=entity.id)
            self.transport.write(packet)

            self.factory.destroy_entity(entity)

    def digging(self, container):
        if container.state != 3:
            return

        bigx, smallx, bigz, smallz = split_coords(container.x, container.z)

        try:
            chunk = self.chunks[bigx, bigz]
        except KeyError:
            self.error("Couldn't dig in chunk (%d, %d)!" % (bigx, bigz))
            return

        oldblock = chunk.get_block((smallx, container.y, smallz))
        newblock = blocks[oldblock].replace
        chunk.set_block((smallx, container.y, smallz), newblock)

        packet = make_packet("block", x=container.x, y=container.y, z=container.z,
            type=newblock, meta=0)
        self.factory.broadcast_for_chunk(packet, bigx, bigz)

        dropblock = blocks[oldblock].drop

        if dropblock != 0:
            entity = self.factory.create_entity(container.x * 32 + 16,
                container.y * 32, container.z * 32 + 16, dropblock)

            packet = make_packet("spawn-pickup", entity=Container(id=entity.id),
                item=dropblock, count=1, x=container.x * 32 + 16,
                y=container.y * 32, z=container.z * 32 + 16, yaw=252,
                pitch=25, roll=12)
            self.transport.write(packet)

            packet = make_packet("create", id=entity.id)
            self.transport.write(packet)

    def build(self, container):
        x = container.x
        y = container.y
        z = container.z

        # Offset coords according to face.
        if container.face == 0:
            y -= 1
        elif container.face == 1:
            y += 1
        elif container.face == 2:
            z -= 1
        elif container.face == 3:
            z += 1
        elif container.face == 4:
            x -= 1
        elif container.face == 5:
            x += 1

        bigx, smallx, bigz, smallz = split_coords(x, z)

        try:
            chunk = self.chunks[bigx, bigz]
        except KeyError:
            self.error("Couldn't build in chunk (%d, %d)!" % (bigx, bigz))
            return

        chunk.set_block((smallx, y, smallz), container.block)

        packet = make_packet("block", x=x, y=y, z=z, type=container.block, meta=0)
        self.factory.broadcast_for_chunk(packet, bigx, bigz)

    def equip(self, container):
        self.player.equipped = container.item

    def quit(self, container):
        print "Client is quitting: %s" % container.message
        self.transport.loseConnection()

    def unhandled(self, container):
        print "Unhandled but parseable packet found!"
        print container

    def disable_chunk(self, x, z):
        del self.chunk_lfu[x, z]
        del self.chunks[x, z]

        packet = make_packet("prechunk", x=x, z=z, enabled=0)
        self.transport.write(packet)

    def enable_chunk(self, x, z):
        self.chunk_lfu[x, z] += 1

        if (x, z) in self.chunks:
            return

        chunk = self.factory.world.load_chunk(x, z)

        packet = make_packet("prechunk", x=x, z=z, enabled=1)
        self.transport.write(packet)

        packet = chunk.save_to_packet()
        self.transport.write(packet)

        for entity in chunk.tileentities:
            packet = entity.save_to_packet()
            #self.transport.write(packet)

        self.chunks[x, z] = chunk

    def dataReceived(self, data):
        self.buf += data

        packets, self.buf = parse_packets(self.buf)

        for header, payload in packets:
            if header in self.factory.hooks:
                self.factory.hooks[header](self, payload)
            else:
                self.handlers[header](payload)

    def challenged(self):
        self.state = STATE_CHALLENGED
        self.entity = self.factory.create_entity()

    def authenticated(self):
        self.state = STATE_AUTHENTICATED

        self.player = Player()
        self.factory.players.add(self)

        packet = make_packet("chat",
            message="%s is joining the game..." % self.username)
        self.factory.broadcast(packet)

        spawn = self.factory.world.spawn
        packet = make_packet("spawn", x=spawn[0], y=spawn[1], z=spawn[2])
        self.transport.write(packet)

        self.player.location.x = spawn[0]
        self.player.location.y = spawn[1]
        self.player.location.stance = spawn[1]
        self.player.location.z = spawn[2]

        tag = self.factory.world.load_player(self.username)
        if tag:
            self.player.load_from_tag(tag)

        packet = self.player.inventory.save_to_packet()
        self.transport.write(packet)
        packet = self.player.crafting.save_to_packet()
        self.transport.write(packet)
        packet = self.player.armor.save_to_packet()
        self.transport.write(packet)

        self.send_initial_chunk_and_location()

        self.ping_loop = LoopingCall(self.update_ping)
        self.ping_loop.start(5)

        self.time_loop = LoopingCall(self.update_time)
        self.time_loop.start(10)

        self.update_chunks()

    def send_initial_chunk_and_location(self):
        bigx, smallx, bigz, smallz = split_coords(self.player.location.x,
            self.player.location.z)

        self.enable_chunk(bigx, bigz)
        chunk = self.chunks[bigx, bigz]

        # This may not play well with recent Alpha clients, which have an
        # unfortunate bug at maximum heights. We have yet to ascertain whether
        # the bug is server-side or client-side.
        height = chunk.height_at(smallx, smallz) + 2
        self.player.location.y = height

        packet = self.player.location.save_to_packet()
        self.transport.write(packet)

    def update_chunks(self):
        print "Sending chunks..."
        x, chaff, z, chaff = split_coords(self.player.location.x,
            self.player.location.z)

        # Perhaps some explanation is in order.
        # The coiterate() function iterates over the iterable it is fed,
        # without tying up the reactor, by yielding after each iteration. The
        # inner part of the generator expression generates all of the chunks
        # around the currently needed chunk, and it sorts them by distance to
        # the current chunk. The end result is that we load chunks one-by-one,
        # nearest to furthest, without stalling other clients. After this is
        # all done, we want to prune any unused chunks.
        d = coiterate(self.enable_chunk(i, j)
            for i, j in
            sorted(itertools.product(
                    xrange(x - 10, x + 10),
                    xrange(z - 10, z + 10)
                ),
                key=lambda t: (t[0] - x)**2 + (t[1] - z)**2
            )
        )

        d.addCallback(lambda chaff: self.prune_chunks())

    def prune_chunks(self):
        if len(self.chunks) > 600:
            print "Pruning chunks..."
            x, chaff, z, chaff = split_coords(self.player.location.x,
                self.player.location.z)
            victims = sorted(self.chunks.iterkeys(),
                key=lambda i: self.chunk_lfu[i])
            for victim in victims:
                if len(self.chunks) < 600:
                    break
                if (x - 10 < victim[0] < x + 10
                    and z - 10 < victim[1] < z + 10):
                    self.disable_chunk(*victim)

    def update_ping(self):
        packet = make_packet("ping")
        self.transport.write(packet)

    def update_time(self):
        packet = make_packet("time", timestamp=self.factory.time)
        self.transport.write(packet)

    def error(self, message):
        self.transport.write(make_error_packet(message))
        self.transport.loseConnection()

    def connectionLost(self, reason):
        self.factory.players.discard(self)

