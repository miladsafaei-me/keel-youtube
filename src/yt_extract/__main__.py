"""`python -m yt_extract ...`

A second way in, for the common case where pip installed the console scripts
into a directory that is not on PATH - typically `Scripts\\` on Windows. This
entry point needs only the interpreter to be findable.
"""

from .cli import main

raise SystemExit(main())
