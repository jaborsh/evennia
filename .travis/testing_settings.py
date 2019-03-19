"""
Evennia settings file.

The available options are found in the default settings file found
here:

/home/griatch/Devel/Home/evennia/evennia/evennia/settings_default.py

Remember:

Don't copy more from the default file than you actually intend to
change; this will make sure that you don't overload upstream updates
unnecessarily.

When changing a setting requiring a file system path (like
path/to/actual/file.py), use GAME_DIR and EVENNIA_DIR to reference
your game folder and the Evennia library folders respectively. Python
paths (path.to.module) should be given relative to the game's root
folder (typeclasses.foo) whereas paths within the Evennia library
needs to be given explicitly (evennia.foo).

If you want to share your game dir, including its settings, you can
put secret game- or server-specific settings in secret_settings.py.

"""

import os

# Use the defaults from Evennia unless explicitly overridden
from evennia.settings_default import *

######################################################################
# Evennia base server config
######################################################################

# This is the name of your game. Make it catchy!
SERVERNAME = "testing_mygame"

# Testing database types

testing_db = os.environ.get("TESTING_DB", None)
print("TESTING_DB='{}'".format(testing_db))

if testing_db == "postgresql":
    print("Loading PostGreSQL database backend.")
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'evennia',
        'USER': 'evennia',
        'PASSWORD': 'password',
        'HOST': 'localhost',
        'PORT': ''    # use default
    }
elif testing_db == "mysql":
    print("Loading MySQL database backend.")
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'evennia',
        'USER': 'evennia',
        'PASSWORD': 'password',
        'HOST': 'localhost',  # or an IP Address that your DB is hosted on
        'PORT': '',  # use default port
    }
else:  # default sqlite3, use default settings
    print("Loading SQlite3 database backend (default).")
    pass


######################################################################
# Settings given in secret_settings.py override those in this file.
######################################################################
try:
    from server.conf.secret_settings import *
except ImportError:
    print("secret_settings.py file not found or failed to import.")
