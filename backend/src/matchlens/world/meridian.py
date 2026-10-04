from matchlens.models.match import PlayerTraits, Role, TeamColors, TeamStyle
from matchlens.world.models import Club, League, SquadPlayer


def player(  # noqa: PLR0913
    number: int, name: str, role: Role, *, pace: int, passing: int, finishing: int, defending: int
) -> SquadPlayer:
    return SquadPlayer(
        number=number,
        name=name,
        role=role,
        traits=PlayerTraits(pace=pace, passing=passing, finishing=finishing, defending=defending),
    )


KESTREL_BAY = Club(
    club_id="kestrel-bay",
    name="Kestrel Bay Athletic",
    short_name="KBA",
    venue="Gullwing Park",
    colors=TeamColors(primary="#0E5E6F", secondary="#F4D35E"),
    formation="4-3-3",
    style=TeamStyle(possession=0.75, press=0.6, directness=0.25),
    starters=(
        player(1, "Tobias Wrenfield", "GK", pace=46, passing=70, finishing=10, defending=82),
        player(2, "Mateo Quillan", "FB", pace=82, passing=76, finishing=38, defending=74),
        player(4, "Soren Halbrook", "CB", pace=66, passing=74, finishing=32, defending=83),
        player(5, "Kwame Ardley", "CB", pace=70, passing=70, finishing=35, defending=85),
        player(3, "Idris Calvane", "FB", pace=84, passing=74, finishing=36, defending=72),
        player(6, "Luca Brenmoor", "DM", pace=64, passing=86, finishing=48, defending=78),
        player(8, "Rafael Ostrin", "CM", pace=70, passing=88, finishing=64, defending=64),
        player(10, "Elias Thornquist", "CM", pace=72, passing=87, finishing=70, defending=60),
        player(7, "Nico Valdane", "W", pace=88, passing=78, finishing=74, defending=40),
        player(9, "Dario Kestell", "ST", pace=80, passing=72, finishing=84, defending=34),
        player(11, "Yusuf Marwick", "W", pace=90, passing=74, finishing=72, defending=38),
    ),
    bench=(
        player(13, "Bram Elsworth", "GK", pace=44, passing=62, finishing=8, defending=76),
        player(15, "Jonah Pellow", "CB", pace=64, passing=66, finishing=30, defending=79),
        player(12, "Aurelio Fenn", "FB", pace=80, passing=70, finishing=34, defending=70),
        player(14, "Teo Ravensworth", "CM", pace=68, passing=80, finishing=60, defending=62),
        player(16, "Felix Dunmore", "DM", pace=62, passing=78, finishing=44, defending=74),
        player(17, "Sami Ockerlind", "W", pace=86, passing=70, finishing=68, defending=36),
        player(19, "Rowan Vesterholt", "ST", pace=78, passing=64, finishing=78, defending=32),
    ),
)

ASHMOOR_ROVERS = Club(
    club_id="ashmoor-rovers",
    name="Ashmoor Rovers",
    short_name="ASR",
    venue="Ashmoor Common",
    colors=TeamColors(primary="#8C1C13", secondary="#F2E8CF"),
    formation="4-2-3-1",
    style=TeamStyle(possession=0.5, press=0.82, directness=0.45),
    starters=(
        player(1, "Piotr Langhorne", "GK", pace=50, passing=60, finishing=12, defending=84),
        player(2, "Emeka Strand", "FB", pace=86, passing=68, finishing=34, defending=78),
        player(5, "Callum Rookwood", "CB", pace=72, passing=62, finishing=36, defending=86),
        player(4, "Andres Vellacor", "CB", pace=74, passing=64, finishing=38, defending=84),
        player(3, "Tariq Hollin", "FB", pace=88, passing=66, finishing=36, defending=76),
        player(6, "Gustav Merrow", "DM", pace=70, passing=76, finishing=46, defending=82),
        player(8, "Ilias Corrander", "CM", pace=76, passing=78, finishing=62, defending=72),
        player(7, "Kofi Ashdown", "W", pace=90, passing=70, finishing=72, defending=46),
        player(10, "Matteo Lindqvar", "AM", pace=78, passing=84, finishing=76, defending=48),
        player(11, "Ruben Calderwick", "W", pace=88, passing=72, finishing=70, defending=44),
        player(9, "Oskar Fennimore", "ST", pace=86, passing=64, finishing=82, defending=40),
    ),
    bench=(
        player(13, "Declan Mott", "GK", pace=46, passing=56, finishing=10, defending=77),
        player(15, "Henrik Saltash", "CB", pace=70, passing=58, finishing=32, defending=80),
        player(12, "Jules Ambry", "FB", pace=84, passing=64, finishing=32, defending=72),
        player(14, "Pavel Drumlin", "CM", pace=74, passing=74, finishing=58, defending=68),
        player(16, "Ade Okanwe", "DM", pace=72, passing=70, finishing=42, defending=78),
        player(17, "Lior Penhallow", "W", pace=89, passing=66, finishing=66, defending=40),
        player(18, "Marek Stavely", "ST", pace=82, passing=60, finishing=78, defending=36),
    ),
)

PORT_HALDEN = Club(
    club_id="port-halden",
    name="Port Halden FC",
    short_name="PHF",
    venue="Halden Quay Stadium",
    colors=TeamColors(primary="#1B2A49", secondary="#E0A458"),
    formation="4-4-2",
    style=TeamStyle(possession=0.38, press=0.4, directness=0.8),
    starters=(
        player(1, "Viktor Branscombe", "GK", pace=44, passing=58, finishing=10, defending=85),
        player(2, "Sean Tolliver", "FB", pace=80, passing=64, finishing=34, defending=74),
        player(4, "Bastian Grue", "CB", pace=62, passing=58, finishing=40, defending=86),
        player(5, "Moses Abernath", "CB", pace=64, passing=60, finishing=42, defending=84),
        player(3, "Leandro Fosk", "FB", pace=82, passing=66, finishing=36, defending=72),
        player(7, "Jaden Quarrie", "W", pace=91, passing=68, finishing=74, defending=38),
        player(8, "Hugo Selwyn", "CM", pace=70, passing=78, finishing=64, defending=66),
        player(6, "Amir Coldwell", "CM", pace=68, passing=76, finishing=58, defending=72),
        player(11, "Finn Harrowgate", "W", pace=89, passing=70, finishing=72, defending=40),
        player(9, "Zeke Marrable", "ST", pace=84, passing=62, finishing=86, defending=34),
        player(10, "Caio Brennard", "ST", pace=78, passing=66, finishing=84, defending=36),
    ),
    bench=(
        player(13, "Ollie Wexcombe", "GK", pace=42, passing=54, finishing=8, defending=78),
        player(15, "Darius Penmarch", "CB", pace=60, passing=56, finishing=36, defending=80),
        player(12, "Kai Ludlow", "FB", pace=80, passing=60, finishing=30, defending=70),
        player(14, "Stellan Moorcroft", "CM", pace=66, passing=74, finishing=56, defending=66),
        player(16, "Remi Castellane", "AM", pace=74, passing=80, finishing=72, defending=42),
        player(17, "Bayo Trenholm", "W", pace=88, passing=64, finishing=68, defending=36),
        player(19, "Gideon Sparrowhawk", "ST", pace=82, passing=58, finishing=80, defending=32),
    ),
)

VELLMONT_CITY = Club(
    club_id="vellmont-city",
    name="Vellmont City",
    short_name="VEL",
    venue="Larkspur Road",
    colors=TeamColors(primary="#2E7D32", secondary="#FFFFFF"),
    formation="4-1-4-1",
    style=TeamStyle(possession=0.52, press=0.45, directness=0.5),
    starters=(
        player(1, "Anders Hallowmere", "GK", pace=48, passing=64, finishing=12, defending=80),
        player(2, "Rico Fairweather", "FB", pace=82, passing=70, finishing=36, defending=74),
        player(5, "Tomasz Kerrow", "CB", pace=68, passing=66, finishing=34, defending=82),
        player(4, "Malik Dunstable", "CB", pace=66, passing=64, finishing=38, defending=83),
        player(3, "Elio Garroway", "FB", pace=80, passing=68, finishing=34, defending=75),
        player(6, "Joaquin Ferrand", "DM", pace=66, passing=80, finishing=46, defending=80),
        player(7, "Theo Lanyon", "W", pace=86, passing=72, finishing=70, defending=42),
        player(8, "Samir Westlake", "CM", pace=72, passing=82, finishing=66, defending=64),
        player(10, "Bjorn Ashgrove", "CM", pace=70, passing=80, finishing=68, defending=66),
        player(11, "Nathaniel Quarrington", "W", pace=87, passing=70, finishing=72, defending=40),
        player(9, "Luka Varnell", "ST", pace=82, passing=68, finishing=84, defending=36),
    ),
    bench=(
        player(13, "Silas Pennock", "GK", pace=44, passing=58, finishing=10, defending=76),
        player(15, "Ibrahim Tallis", "CB", pace=66, passing=60, finishing=34, defending=78),
        player(12, "Max Corbridge", "FB", pace=78, passing=64, finishing=32, defending=70),
        player(14, "Dmitri Ashenden", "CM", pace=68, passing=76, finishing=60, defending=62),
        player(16, "Kenji Moorland", "DM", pace=64, passing=74, finishing=42, defending=76),
        player(17, "Gabriel Thistlewood", "W", pace=86, passing=66, finishing=66, defending=38),
        player(18, "Ansel Brightwater", "ST", pace=80, passing=62, finishing=80, defending=34),
    ),
)

MERIDIAN_LEAGUE = League(
    name="Meridian League",
    clubs=(KESTREL_BAY, ASHMOOR_ROVERS, PORT_HALDEN, VELLMONT_CITY),
)
