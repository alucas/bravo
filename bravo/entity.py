from math import pi, atan2, degrees
from random import uniform

from twisted.python import log

from bravo.inventory import Equipment, ChestStorage
from bravo.location import Location
from bravo.packets.beta import make_packet
from bravo.utilities.ai import closest_player, check_collision
from twisted.internet.task import LoopingCall

class Entity(object):
    """
    Class representing an entity.

    Entities are simply dynamic in-game objects. Plain entities are not very
    interesting.
    """

    name = "Entity"

    def __init__(self, location=None, eid=0, **kwargs):
        """
        Create an entity.

        This method calls super().
        """

        super(Entity, self).__init__()

        self.eid = eid

        if location is None:
            self.location = Location()
        else:
            self.location = location

    def __repr__(self):
        return "%s(eid=%d, location=%s)" % (self.name, self.eid, self.location)

    __str__ = __repr__

class Player(Entity):
    """
    A player entity.
    """

    name = "Player"

    def __init__(self, username="", **kwargs):
        """
        Create a player.

        This method calls super().
        """

        super(Player, self).__init__(**kwargs)

        self.username = username
        self.inventory = Equipment()

        self.equipped = 0

    def save_to_packet(self):
        """
        Create a "player" packet representing this entity.
        """

        yaw = int(self.location.theta * 255 / (2 * pi)) % 256
        pitch = int(self.location.phi * 255 / (2 * pi)) % 256

        item = self.inventory.holdables[self.equipped]
        if item is None:
            item = 0
        else:
            item = item[0]

        return make_packet("player",
            eid=self.eid,
            username=self.username,
            x=self.location.x,
            y=self.location.y,
            z=self.location.z,
            yaw=yaw,
            pitch=pitch,
            item=item
        )

    def save_equipment_to_packet(self):
        """
        Creates packets that include the equipment of the player. Equipment
        is the item the player holds and all 4 armor parts.
        """

        packet = ""
        slots = (self.inventory.holdables[0], self.inventory.armor[3],
                 self.inventory.armor[2], self.inventory.armor[1],
                 self.inventory.armor[0])

        for slot, item in enumerate(slots):
            if item is None:
                continue

            primary, secondary, count = item
            packet += make_packet("entity-equipment",
                eid=self.eid,
                slot=slot,
                primary=primary,
                secondary=secondary
            )
        return packet

class Painting(Entity):
    """
    A painting on a wall.
    """

    name = "Painting"

    def __init__(self, direction=1, motive="", **kwargs):
        """
        Create a painting.

        This method calls super().
        """

        super(Painting, self).__init__(**kwargs)

        self.direction = direction
        self.motive = motive

    def save_to_packet(self):
        """
        Create a "painting" packet representing this entity.
        """

        return make_packet("painting",
            eid=self.eid,
            title=self.motive,
            x=self.location.x,
            y=self.location.y,
            z=self.location.z,
            direction=self.direction
        )

class Pickup(Entity):
    """
    Class representing a dropped block or item.

    For historical and sanity reasons, this class is called Pickup, even
    though its entity name is "Item."
    """

    name = "Item"

    def __init__(self, item=(0, 0), quantity=1, **kwargs):
        """
        Create a pickup.

        This method calls super().
        """

        super(Pickup, self).__init__(**kwargs)

        self.item = item
        self.quantity = quantity

    def save_to_packet(self):
        """
        Create a "pickup" packet representing this entity.
        """

        return make_packet("pickup",
            eid=self.eid,
            primary=self.item[0],
            secondary=self.item[1],
            count=self.quantity,
            x=self.location.x * 32 + 16,
            y=self.location.y * 32,
            z=self.location.z * 32 + 16,
            yaw=0,
            pitch=0,
            roll=0
        )

class Mob(Entity):
    """
    A creature.
    """
    def __init__(self, **kwargs):
        """
        Create a mob

        This method calls super().
        """

        super(Mob, self).__init__(**kwargs)
        self.manager = None
        self.offsetlist = ((.5,0,.5),(-.5,0,.5),(.5,0,-.5),(-.5,0,-.5))
    name = "Mob"
    type = "mob"

    metadata = {0: ("byte", 0)}

    def run(self,factory):
        self.loop = LoopingCall(self.update,factory)
        self.loop.start(.2)

    def save_to_packet(self):
        """
        Create a "mob" packet representing this entity.
        """

        return make_packet("mob",
            eid=self.eid,
            type=self.type,
            x=self.location.x * 32 + 16,
            y=self.location.y * 32,
            z=self.location.z * 32 + 16,
            yaw=0,
            pitch=0,
            metadata=self.metadata
        )

    def save_location_to_packet(self):
        return make_packet("teleport",
            eid=self.eid,
            x=self.location.x * 32 + 16,
            y=self.location.y * 32,
            z=self.location.z * 32 + 16,
            yaw=int(self.location.yaw),
            pitch=int(self.location.pitch),
        )

    def update(self, factory):
        """
        Update this mob's location with respect to a factory.
        """
        clamp = lambda n: max(min(.5, n), -.5)
        # XXX  Discuss appropriate style with MAD
        player = closest_player(factory,
                                (self.location.x,
                                self.location.y,
                                self.location.z),
                                16)
        if player == None:
            vector = (uniform(-.5,.5),
                      uniform(-.5,.5),
                      uniform(-.5,.5))
            target = (self.location.x + vector[0],
                      self.location.y + vector[1],
                      self.location.z + vector[2])
        else:
            target = (player.location.x,
                      player.location.y,
                      player.location.z)
            vector = (clamp(target[0] - self.location.x),
                      clamp(target[1] - self.location.y),
                      clamp(target[2] - self.location.z))

        new_position = (vector[0] + self.location.x,
                        vector[1] + self.location.y,
                        vector[2] + self.location.z,)

        new_pitch = int(atan2((self.location.z - target[2]),
            (self.location.x - target[0] )) + pi/2)
        if new_pitch < 0 :
            new_pitch = 0

        can_go = check_collision(new_position,self.offsetlist, factory)

        if can_go:
            self.location.x = new_position[0]
            self.location.y = new_position[1]
            self.location.z = new_position[2]
            self.location.theta = new_pitch
            factory.broadcast(self.save_location_to_packet())
        else:
            pass


class Chuck(Mob):
    """
    A cross between a duck and a chicken.
    """

    name = "Chicken"
    type = "chuck"

class Cow(Mob):
    """
    Large, four-legged milk containers.
    """

    name = "Cow"
    type = "cow"

class Creeper(Mob):
    """
    A creeper.
    """

    name = "Creeper"

    metadata = {0: ("byte", 0), 17: ("byte", 0)}

    def __init__(self, aura=False, **kwargs):
        """
        Create a creeper.

        This method calls super()
        """

        super(Creeper, self).__init__(**kwargs)

        self.aura = aura

    def save_to_packet(self):
        metadata = self.metadata.copy()

        aura = 0
        if self.aura:
            aura |= 0x1
        metadata[17] = "byte", aura

        return make_packet("mob",
            eid=self.eid,
            type="creeper",
            x=self.location.x * 32 + 16,
            y=self.location.y * 32,
            z=self.location.z * 32 + 16,
            yaw=0,
            pitch=0,
            metadata=metadata
        )

class Ghast(Mob):
    """
    A sad ghost
    """

    name = "Ghast"
    type = "ghast"

class GiantZombie(Mob):
    """
    A giant zombie
    """

    name = "GiantZombie"
    type = "giant_zombie"

class Pig(Mob):
    """
    A provider of bacon and piggyback rides.
    """

    name = "Pig"

    metadata = {0: ("byte", 0), 16: ("byte", 0)}

    def __init__(self, saddle=False, **kwargs):
        """
        Create a pig.

        This method calls super()
        """

        super(Pig, self).__init__(**kwargs)

        self.saddle = saddle

    def save_to_packet(self):
        # Prepare metadata.
        metadata = self.metadata.copy()
        metadata[16] = "byte", self.saddle

        return make_packet("mob",
            eid=self.eid,
            type="pig",
            x=self.location.x * 32 + 16,
            y=self.location.y * 32,
            z=self.location.z * 32 + 16,
            yaw=0,
            pitch=0,
            metadata=metadata
        )

class PigZombie(Mob):
    """
    A zombie pigman.
    """

    name = "PigZombie"
    type = "pigman"

class Sheep(Mob):
    """
    A wooly mob.
    """

    name = "Sheep"

    metadata = {0: ("byte", 0), 16: ("byte", 0)}

    def __init__(self, sheared=False, color=0, **kwargs):
        """
        Create a sheep.

        This method calls super().
        """

        super(Sheep, self).__init__(**kwargs)

        self.sheared = sheared
        self.color = color

    def save_to_packet(self):
        # Prepare metadata.
        metadata = self.metadata.copy()
        color = self.color
        if self.sheared:
            color |= 0x10
        metadata[16] = "byte", color

        return make_packet("mob",
            eid=self.eid,
            type="sheep",
            x=self.location.x * 32 + 16,
            y=self.location.y * 32,
            z=self.location.z * 32 + 16,
            yaw=0,
            pitch=0,
            metadata=metadata
        )

class Skeleton(Mob):
    """
    An archer skeleton.
    """

    name = "Skeleton"
    type = "skeleton"

class Slime(Mob):
    """
    A gelatinous blob.
    """

    name = "Slime"

    metadata = {0: ("byte", 0), 16: ("byte", 0)}

    def __init__(self, size=1, **kwargs):
        """
        Create a slime.

        This method calls super().
        """

        super(Slime, self).__init__(**kwargs)

        self.size = size

    def save_to_packet(self):
        # Prepare metadata.
        metadata = self.metadata.copy()
        metadata[16] = "byte", self.size

        return make_packet("mob",
            eid=self.eid,
            type="slime",
            x=self.location.x * 32 + 16,
            y=self.location.y * 32,
            z=self.location.z * 32 + 16,
            yaw=0,
            pitch=0,
            metadata=metadata
        )

class Spider(Mob):
    """
    A spider.
    """

    name = "Spider"
    type = "spider"

class Squid(Mob):
    """
    An aquatic source of ink.
    """

    name = "Squid"
    type = "squid"

class Wolf(Mob):
    """
    A wolf.
    """

    name = "Wolf"

    metadata = {0: ("byte", 0), 16: ("byte", 0)}

    def __init__(self, owner=None, angry=False, sitting=False, **kwargs):
        """
        Create a wolf.

        This method calls super().
        """

        super(Wolf, self).__init__(**kwargs)

        self.owner = owner
        self.angry = angry
        self.sitting = sitting

    def save_to_packet(self):
        # Prepare metadata.
        metadata = self.metadata.copy()
        props = 0
        if self.sitting:
            props |= 0x1
        if self.angry:
            props |= 0x2
        if self.owner:
            props |= 0x4
        metadata[16] = "byte", props

        return make_packet("mob",
            eid=self.eid,
            type="wolf",
            x=self.location.x * 32 + 16,
            y=self.location.y * 32,
            z=self.location.z * 32 + 16,
            yaw=0,
            pitch=0,
            metadata=metadata
        )

class Zombie(Mob):
    """
    A zombie.
    """

    name = "Zombie"
    type = "zombie"

entities = dict((entity.name, entity)
    for entity in (
        Chuck,
        Cow,
        Creeper,
        Ghast,
        GiantZombie,
        Painting,
        Pickup,
        Pig,
        PigZombie,
        Player,
        Sheep,
        Skeleton,
        Spider,
        Squid,
        Wolf,
        Zombie,
    )
)

class Tile(object):
    """
    An entity that is also a block.

    Or, perhaps more correctly, a block that is also an entity.
    """

    name = "GenericTile"

    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def load_from_packet(self, container):

        log.msg("%s doesn't know how to load from a packet!" % self.name)

    def save_to_packet(self):

        log.msg("%s doesn't know how to save to a packet!" % self.name)

        return ""

class Chest(Tile):
    """
    A tile that holds items.
    """

    name = "Chest"

    def __init__(self, *args, **kwargs):
        super(Chest, self).__init__(*args, **kwargs)

        self.inventory = ChestStorage()

class Furnace(Tile):
    """
    A tile that converts items to other items, using specific items as fuel.
    """

    name = "Furnace"

    def __init__(self, *args, **kwargs):
        super(Furnace, self).__init__(*args, **kwargs)

        self.inventory = ChestStorage()

class MobSpawner(Tile):
    """
    A tile that spawns mobs.
    """

    name = "MobSpawner"

class Music(Tile):
    """
    A tile which produces a pitch when whacked.
    """

    name = "Music"

class Sign(Tile):
    """
    A tile that stores text.
    """

    name = "Sign"

    def __init__(self, *args, **kwargs):
        super(Sign, self).__init__(*args, **kwargs)

        self.text1 = ""
        self.text2 = ""
        self.text3 = ""
        self.text4 = ""

    def load_from_packet(self, container):
        self.x = container.x
        self.y = container.y
        self.z = container.z

        self.text1 = container.line1
        self.text2 = container.line2
        self.text3 = container.line3
        self.text4 = container.line4

    def save_to_packet(self):
        packet = make_packet("sign", x=self.x, y=self.y, z=self.z,
            line1=self.text1, line2=self.text2, line3=self.text3,
            line4=self.text4)
        return packet

tiles = dict((tile.name, tile)
    for tile in (
        Chest,
        Furnace,
        MobSpawner,
        Music,
        Sign,
    )
)
