from discord import PartialEmoji, Status

CHECK_EMOTE = PartialEmoji(name='Check', id=941933851289194547)
CROSS_EMOTE = PartialEmoji(name='Cross', id=941933851096285225)
MAGNIFYING_GLASS = PartialEmoji(name='MagnifyingGlass', id=957976796031234088)
ONE = PartialEmoji(name='1_', id=959816930175377428)
ARROW_RIGHT = PartialEmoji(name='Arrow_Right', id=959816930200547348)
SHIELD = PartialEmoji(name='Shield', id=959818961694900254)
STAFF = PartialEmoji(name='Staff', id=959818962152067083)
TWO = PartialEmoji(name='2_', id=959820793011912774)
INFO = PartialEmoji(name='Info', id=959820793083203604)
MUTED = PartialEmoji(name='Muted', id=960283053056458752)
BANNED = PartialEmoji(name='Banned', id=960283593907769374)
DATABASE = PartialEmoji(name='Database', id=960877642914070539)
MODERATOR = PartialEmoji(name='Moderator', id=962706155304542300)
PURPLE_MAGNIFYING_GLASS = PartialEmoji(name='MagnifyingGlass', id=962706158227976222)
RUBBISH_BIN = PartialEmoji(name='RubbishBin', id=962706161176551464)
CROWN_EMOTE = PartialEmoji(name='Crown', id=942047321779212358)
LEADERBOARD_BELL = PartialEmoji(name='lb_bell', id=942050031077318676)
HOURGLASS = PartialEmoji(name='Hourglass', id=966965405858037760)
ONLINE = PartialEmoji(name='Online', id=967339974125051904)
IDLE = PartialEmoji(name='Idle', id=967339975345577984)
OFFLINE = PartialEmoji(name='Offline', id=967339976763248640)
GREY_BIN = PartialEmoji(name='Bin', id=955392605364039692)
JOIN = PartialEmoji(name='Join', id=972543725614035104)
LEAVE = PartialEmoji(name='Leave', id=972543826549948536)
FOLDER_ADD = PartialEmoji(name='add', id=995457312468766830)
FOLDER_EDIT = PartialEmoji(name='edit', id=995457310551986227)
FOLDER_DELETE = PartialEmoji(name='remove', id=995457313781592084)
RUBBISH_BIN_2 = PartialEmoji(name='delete', id=995461063812321360)
TAG_NAME = PartialEmoji(name='name', id=995646004747587614)
WARNING = PartialEmoji(name='warning', id=996096595605078116)
FOLDER_ADD_2 = PartialEmoji(name='folder', id=998113320441761843)
DOCUMENT = PartialEmoji(name='document', id=998113322052358266)
PROFILE = PartialEmoji(name='profile', id=998113324044668991)
WEBSITE = PartialEmoji(name='website', id=998088413355966516)
CHECK_BOX = PartialEmoji(name='Check', id=1008351880411353098)
TEXT_CHANNEL = PartialEmoji(name='TextChannel', id=923462310511648809)

# For config dashboard
PUNISHMENTS = PartialEmoji(name='punishments', id=983124680087044206)
ROLES = PartialEmoji(name='roles', id=983123365432807434)
NOTICE = PartialEmoji(name='notice', id=983132283047395419)
SELECTION = PartialEmoji(name='selection', id=983133504982368276)
PANEL = PartialEmoji(name='info', id=983123735013896284)

# For embed builder
POWER = PartialEmoji(name='Power', id=986644007042039858)
GLOBE = PartialEmoji(name='Globe', id=986671326167183380)
PLUS = PartialEmoji(name='Plus', id=986671323386363934)
MENU = PartialEmoji(name='Menu', id=986696963414171658)
PEN = PartialEmoji(name='Pen', id=986697530995789834)
COLOUR = PartialEmoji(name='Colour', id=986697629616459836)
ADD = PartialEmoji(name='Add', id=986697664362074193)
IMAGE = PartialEmoji(name='Image', id=986697286241382531)


LEADERBOARD_EMOTES = [
    PartialEmoji(name='lb1', id=942016076873617498),
    PartialEmoji(name='lb2', id=942016079142727680),
    PartialEmoji(name='lb3', id=942016081613164636),
    PartialEmoji(name='lb4', id=942016084628869160),
    PartialEmoji(name='lb5', id=942016086537297941),
    PartialEmoji(name='lb6', id=942016088852561951),
    PartialEmoji(name='lb7', id=942016100684681217),
    PartialEmoji(name='lb8', id=942016103490654278),
    PartialEmoji(name='lb9', id=942016105315205231),
    PartialEmoji(name='lb10', id=942016108439949312)
]


BADGES = {
    'hypesquad': PartialEmoji(name='DiscordHypesquad', id=923462320724770837),
    'hypesquad_bravery': PartialEmoji(name='DiscordBravery', id=923462327666343946),
    'hypesquad_brilliance': PartialEmoji(name='DiscordBrilliance', id=923462328756883517),
    'hypesquad_balance': PartialEmoji(name='DiscordBalance', id=923462321949540363),
    'staff': PartialEmoji(name='DiscordStaff', id=923462324138934363),
    'discord_certified_moderator': PartialEmoji(name='CertifiedModerator', id=923477391362371594),
    'partner': PartialEmoji(name='DiscordPartner', id=923462291364642826),
    'bug_hunter': PartialEmoji(name='DiscordBugHunter', id=923462292597792778),
    'bug_hunter_level_2': PartialEmoji(name='DiscordBugHunterLevel2', id=923462318573117440),
    'early_supporter': PartialEmoji(name='DiscordEarlySupporter', id=923462325795713085),
    'early_verified_bot_developer': PartialEmoji(name='DiscordBotDev', id=923462295114367026),
}

STATUSES = {
    Status.online: "<:Online:923462308397723688>",
    Status.offline: "<:Offline:923462315389648977>",
    Status.idle: "<:Idle:923462305444921375>",
    Status.dnd: "<:DnD:923462313875496980>"
}
