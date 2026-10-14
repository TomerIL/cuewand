Cuewand 2.3 - run your slides from your phone
=============================================

Your phone becomes the remote for PowerPoint: Next and Back, your speaker
notes, the clock, and a laser pointer. Nothing is installed on the phone: it
scans a code and a web page opens.


What it is for, and what it is not
----------------------------------
Cuewand is for your own Windows laptop with PowerPoint, set up before the
talk. That is the only place it has run.

It is not for a lectern computer you meet five minutes before you speak (it
needs Python on the computer), and there is no Mac version.

Keep your clicker in your pocket. The two work side by side: a press on the
clicker shows up on the phone, and the clock starts with the first advance
whichever of them made it.

What has and has not been tried is listed at the end. Read it before you
rely on Cuewand in front of a room.


Start
-----
1. Unzip this folder anywhere on the computer that shows the slides.
2. Double-click "Start Cuewand.bat".
   It needs Python 3.8 or newer (python.org). The very first time, it
   installs one Python package, pywin32, which is what talks to PowerPoint;
   that needs the internet once. The window must then say
   "PowerPoint connection: ready."
3. A page opens in your browser with a large code. Point the phone's camera
   at it. No camera, or it will not scan? The page also shows a short
   address and a 6-digit number to type on the phone.
4. Open your deck in PowerPoint and give Cuewand a moment. It makes a
   picture of every slide now, while no slide show runs, so that it never
   has to ask PowerPoint for one during your talk. The page on the computer and
   the phone both show the progress.
5. On the phone: Setup asks for the talk length and the alerts (everything
   else is under "More options"), then Continue. Cuewand checks the
   connection, PowerPoint, your notes, the screen and vibration, and gives
   one answer. The button under that answer starts the slide show.

Two taps from Setup to your first slide. Keep the Cuewand window open while
you present; close it to stop.


Before an important talk
------------------------
Prove it on your deck   Open the deck, then double-click "Test Cuewand.bat".
                        It makes the pictures, starts the slide show, walks
                        the whole deck forwards and backwards about 200
                        presses, and checks after every press that the show
                        is exactly where it should be. It ends with either
                        "every press landed exactly once" or a list of what
                        went wrong, and saves that as cuewand_selftest.txt
                        (every press in detail: cuewand_selftest.log). It also
                        names the slides that are slow to draw, the slides
                        after which PowerPoint is slow to answer, and any
                        press PowerPoint took without moving. Close Cuewand
                        first, and do not touch the computer while the test
                        runs (a few minutes).

Internet link, ahead    If you may need the internet link at the venue,
of time                 double-click "Get the internet link ready.bat" at
                        home. It downloads the 55 MB program then, not in
                        front of the room.

At the venue            Run the check on the phone again (Menu, "Run the
                        ready check again"). If the phone cannot open the
                        page, see "The phone cannot open the page" below.


The talk view
-------------
Top row           Where you are (slide 3 of 26, and a dot for each step on
                  the slide; "black" while the screen is blacked out), then
                  two buttons: Menu and Slides.

Two buttons       Back and Next (Next is the big one). A press counts for
                  the button your thumb landed on, even if it slides; slide
                  right off the buttons and the press is cancelled, and
                  says so. Setup can swap them for a left hand, and can
                  switch swiping on if you like it.

The clock         The Next button is the clock. It shows the time left, its
                  level sinks as the talk goes, the whole button turns
                  amber when time is short and red when you are over. The
                  clock starts with your first Next (or the first press on
                  a clicker or the keyboard) and stops when the slide show
                  ends. Start the show again from the first slide and the
                  clock starts from zero; start it again from any other
                  slide and it carries on. A clock you paused yourself is
                  left alone. Paused shows as a framed word. The time
                  never leaves the button: while it shows "Slide 8" or
                  "Sending", the time moves to its bottom line. The digits
                  are dark where the level covers them and light above it,
                  so they read wherever the level is.

What a press did  Named on the button as soon as PowerPoint has taken it:
                  "Slide 8", "Step 2 of 3", "No steps shown", "At the
                  start". (On a slide with large GIFs PowerPoint can take a
                  few seconds to confirm where it is; the phone does not
                  wait for that.) Each outcome also
                  has its own flash, so the corner of your eye is enough:
                  white ring inside the edge = new slide, ring in the
                  middle = a step on the same
                  slide, the Back button = back, dashed frame = nothing
                  moved, amber bars above and below = last slide, red
                  cross = not done.
                  On Android each has its own vibration too: one tick =
                  new slide, soft tick = a step, double = back, long = last
                  slide, three short = nothing moved, five short = not
                  done. iPhones do not let a web page vibrate.

When something    It is said on the Next button, in words:
is wrong          "Sending"            the press is on its way (slow link)
                  "Still on its way"   no answer after 3 seconds, but the
                                       link works: PowerPoint is slow
                  "Checking the link"  no answer after 3 seconds, and the
                                       regular updates have stopped too
                  "On its way"         PowerPoint has it and is slow; it
                                       will land once. Do not press again.
                  "PowerPoint is busy" PowerPoint never took it. Try again.
                  "Slide had moved"    the show had already changed (a
                                       clicker, another phone): nothing
                                       was done, so nothing is skipped.
                  "Nothing moved"      PowerPoint took the press but used
                                       it to finish bringing the slide up
                                       (a transition or an animation still
                                       playing). Press again. Cuewand
                                       holds a quick press until the slide's
                                       transition is over, and sends it once
                                       more if PowerPoint still swallows
                                       it, so you should rarely see this.
                  "No answer"          the computer did not answer. The
                                       phone asks it what became of the
                                       press and tells you, just above the
                                       buttons: "did arrive" or "did not
                                       arrive".
                  "No connection"      dashed red edge; the slide and notes
                                       dim and say "Last known". The phone
                                       notices within about ten seconds,
                                       and within about three when it is
                                       back.
                  A press can never count twice: each one carries a name
                  tag, and the computer refuses a tag it has seen. A second
                  Next within a second of the first waits its turn ("+1");
                  after that, presses made while one is still on its way
                  are refused out loud, never fired late.

Pace              With a rehearsal, the line under the time says "On pace",
                  "0:40 ahead" or "1:10 behind", measured against that run
                  stretched or squeezed to your talk length. Without one,
                  Cuewand gives no figure; it only says so when you are
                  clearly behind an even split. See Rehearsal below.

Sections          If your deck has PowerPoint sections (Home, Section), the
                  section's name shows above the notes for a moment when
                  it starts ("RESULTS · 1/4"). With a rehearsal, an amber
                  notch on each edge of Next marks where the level should
                  be when the section ends, and the line above the notes
                  says "Results · move on" while you are more than half a
                  minute past it. The only number on screen stays the one
                  on Next.

Notes             The first line large, the rest underneath. They fade at
                  the bottom when there is more to scroll. Cuewand reads
                  them before the slide show starts and keeps checking for
                  edits until it does, so a note you changed just before
                  the talk is the one you see. It does not read them during
                  the show (on a deck with large GIFs that kept PowerPoint
                  busy for seconds): a note changed during the show
                  appears the next time you start it. If Cuewand itself
                  is restarted during a show, it reads each slide's notes
                  when that slide first comes up, which can slow that one
                  press a little.

Notes per step    Write [click] in your notes where an animation step
                  starts. The text before the first [click] is for the
                  slide as it comes up; each [click] starts the next step.
                  The phone then shows only what to say now ("Step 2 of
                  3"), with the next step's first line under it ("Next
                  click: ..."), and on the last step the next slide's
                  first line. "Whole note" shows all of it, the current
                  step marked. The step you are on keeps at least two
                  lines in view: "Next click" takes one line (two when
                  there is room) and steps aside on a short screen, and
                  only if that is not enough the notes get a little
                  smaller. If the marks do not match the slide's steps,
                  the whole note shows and says why; the ready check lists
                  those slides.

Text size         Menu, "Text size": a bar with A-, the size and A+ covers
                  Back and Next until Done, so the notes stay in view while
                  you change it. 90 to 200 %. The notes follow it fully,
                  the rest of the screen up to 150 %. From 150 % the slide
                  picture steps aside (turn it back on in Setup) and the
                  top buttons become icons. Where room runs short the top
                  row says "7 /26", on a short Next the word "Next" gives
                  way rather than the time shrinking, and "Whole note"
                  becomes an icon. On an iPhone the first size follows the
                  phone's own text size.

Slide picture     Hold it to point: PowerPoint's red laser dot follows your
                  finger on the big screen and goes when you lift. A brush
                  of the hand does nothing. The picture shows the finished
                  slide, every animation step revealed. If you changed
                  slides without saving and a picture is old, Setup has
                  "Make the slide pictures again" under More options.

Last slide        Next there only says "Last slide", however often you
                  press it. You cannot walk off the end by accident, and
                  the phone never changes screen by itself. For the other
                  slides, tap Slides. On a hidden backup slide you jumped
                  to, it says "Backup slide" and where Back goes; on a
                  phone that did not make the jump, "Backup slide · Slides
                  to go back".

Turning the phone Landscape puts the slide on the left and the notes with
                  Back and Next on the right. A tablet gets a larger
                  layout; in landscape, a presenter view. After a turn the
                  layout waits a moment and Back/Next ignore presses for a
                  second, so a press made as the buttons move does nothing;
                  the button says "Layout changed · Press again". If the
                  phone will lie flat, turn off auto-rotate.

Slide timers      If a slide has its own timer in PowerPoint, a line above
                  the notes says so. Next still works sooner.


Slides
------
Top right. Every slide as a grid, by section: tap one to jump to it. Hidden
slides are there too, marked "Hidden", which is what you want when a
question needs a backup slide. "Find a slide" at the top finds a word in a
title, on a slide or in its notes, or a slide number; while you type, the
list fills the space above the keyboard, and the first tap only closes the
keyboard, so a mistap cannot change the big screen. After a jump to a
hidden backup slide, Back (here and in the talk) says "Back to slide 12"
and takes you there; once a press lands on an ordinary slide, Back is
plain Back again. Tip: hide your backup slides in PowerPoint (right-click
the slide, Hide Slide); only a jump to a hidden slide offers the way back.
On a tablet the grid runs on without gaps, each section's name on its
first slide. Under the grid are Black out,
Back and Next (mirrored for a left hand). This small Next shows the time
and, unlike the big one, can go past the last slide. The buttons ignore
the first second after the grid opens, so a late tap does nothing. "Back
to talk" returns.


Menu
----
The clock         Start, pause, resume, reset (reset asks twice, then
                  offers Undo for ten seconds); one minute more or less.
The slide show    Black out the screen.
Co-presenters     When two phones are connected: pass the slides to the
                  other phone, take them, or let every phone press. See
                  Co-presenters below.
Rehearsal         Rehearse now (whenever it would move the show or restart
                  the clock it asks twice, and afterwards it offers Undo,
                  which returns to the slide you were on); Where the time
                  went, by section; forget a rehearsal.
This phone        Text size; Setup (talk length, alerts, your name, what
                  this phone shows, left hand, motion); Run the ready check
                  again.
Ending            In red: End the slide show; Start over, which ends the
                  slide show, clears the clock and goes back to Setup.
                  Both ask twice.


Co-presenters
-------------
Any number of phones can connect; by default every one can press Next.
Give each phone your name in Setup. Before a show, a phone with no name is
asked for one when another phone is there; during a show nothing pops up
(a phone that joins is named for a moment above the notes), and Menu ›
Co-presenters has "Name this phone".
In the Menu, "Pass the slides to Ana" makes Ana's phone the only one that
presses; the others follow along with the slide, the notes and the clock,
under a band that says "Following Ana", and their buttons are hatched.
To take the slides back, hold Next for a moment (a ring fills), or press
"Take" in the band twice. If the phone with the slides closes its page or
goes quiet for eight seconds, the band says so and the slides can be taken
at once. Both phones are told on their Next button. The computer refuses
presses from a phone that does not have the slides. The laptop's own
clicker and keyboard always work. The pairing page lists the phones by
name.


Rehearsal
---------
Start one from the Menu, or with "Start a rehearsal" on the start screen,
and talk through every slide at real speed. While it runs, a band with a
red dot under the top row says so on every screen, with Stop beside it. Stop offers
"Save this rehearsal", "Discard it" and "Keep rehearsing", and tells you
when a rehearsal is too short to save or covers too little of the deck to
be used. "Where the time went" then shows the time on each slide, and in a
real talk the same view puts your rehearsal next to it, fitted to the talk
length. A rehearsal that skipped more than a fifth of the slides is kept
but not used for pace. Rehearsals are stored per deck, by file name.


The phone cannot open the page
------------------------------
Same Wi-Fi        The default. Phone and computer on the same network.
                  When Windows asks about the firewall, tick Public as
                  well as Private, then Allow. It asks only once, and a
                  hotel, venue or phone-hotspot network counts as Public:
                  with Private alone, phones on those networks cannot
                  reach the computer. Later, either set the network to
                  Private (Settings, Network & internet, the network's
                  properties) or allow Python for Public networks under
                  "Allow an app through firewall".
                  University, hotel and conference Wi-Fi often stops
                  devices reaching each other. Then:

Phone's hotspot   Turn on the hotspot on your phone and connect the
                  computer to it. The code on the computer changes by
                  itself; scan it again. The slides do not use your mobile
                  data.

Over the internet On the pairing page choose "Over the internet". The
                  phone needs data and the computer needs the internet. It
                  also lets a co-presenter elsewhere run the slides. It
                  uses Cloudflare's free tunnel service (no account, no
                  promise that it stays up). Cuewand downloads one fixed
                  version of Cloudflare's program and checks it is the
                  genuine file before running it. Cuewand tests the link
                  every ten seconds by reaching itself through it, and
                  says so under the code.

If the pairing page has waited twenty seconds with no phone, it shows these
steps by itself.


If Cuewand is closed in the middle of a talk
--------------------------------------------
PowerPoint carries on; only the phone stops. Start Cuewand again: it comes
back with the same code, the same clock and the same time on each slide,
and the phone reconnects by itself. Nobody has to walk back to scan
anything, except over the internet link: its address changes with every
start, so turn it on again on the pairing page and scan the new code. A clock that was running carries on as if nothing happened when
Cuewand was closed for less than a quarter of an hour; after longer it waits
where it was. Codes last twelve hours from when they were made. To cut
every phone off sooner, press "Make new codes" on the pairing page, or
start with --new-codes.

A second Cuewand started by mistake does not run; it opens the pairing page
of the one already running.


Who can control your slides
---------------------------
Anyone who has the code or the 6-digit number, for as long as Cuewand runs.
Closing Cuewand stops everything, but it does not cancel the codes: started
again within twelve hours of making them, Cuewand accepts the same ones. To
cancel them, press "Make new codes". The codes are kept in
cuewand_session.json in this folder, so anyone who can read this folder can
read them. A phone that sends eight wrong numbers in a minute is locked
out for a minute; other phones are not affected. The pairing page and its
buttons answer only this computer: not a phone, not another computer on the
network, and not the internet link. Each device can hold only a few
connections open at once, so one cannot crowd the others out.
On "Same Wi-Fi" nothing is encrypted: someone on the same network who
captures the traffic could read your notes and press Next. On a network
you do not trust, use your phone's hotspot or the internet link.


What Cuewand sends, and to whom
-------------------------------
Nothing to the author, and nothing to anyone else unless you use one of
the three things below. There are no accounts, no analytics and no
tracking.
- Your notes, slide pictures and presses travel only between the laptop
  and your phone: over your Wi-Fi or hotspot, or, with the internet link,
  through Cloudflare's servers, which relay it encrypted on the way.
- On its first run on Windows, Cuewand downloads one Python package,
  pywin32, from PyPI (the Python package index).
- "Get the internet link ready.bat" downloads Cloudflare's program,
  cloudflared, from Cloudflare's own GitHub page. The internet link then
  uses Cloudflare's free "quick tunnels", which Cloudflare says are meant
  for testing and development, with no uptime guarantee. For an
  important talk, rehearse with the link you will use.
What stays on the laptop, in this folder: cuewand.log (the names of phones,
their network addresses, the deck's file name and every press),
cuewand_session.json (the codes and the clock), cuewand_rehearsals.json (the
deck name and the time on each slide) and the self-test files. The phone
keeps its code, its name and its settings in its own browser.


Not PowerPoint?
---------------
With no presentation open in PowerPoint, Next and Back press the right and
left arrow keys on the computer. That works with Google Slides, a PDF in
full screen and so on: click into that window first. No pictures, notes or
pace in this mode; holding the picture area moves the mouse pointer.
While a deck is open in PowerPoint and no slide show runs, the phone offers
Start instead of Next and Back: an arrow key in PowerPoint's editing window
would move something in your deck.


If something does not work
--------------------------
The file cuewand.log in this folder says why. It lists every phone that
connects (and whether it came over the internet link), every press with its
name tag, where it was made from, what became of it and how long PowerPoint
took, every refused request, and why the internet link last failed. The log
of the run before is cuewand.previous.log. Send both.
Before you post a log anywhere public (a GitHub issue, say), replace the
deck's file name, phone names and network addresses in it.

Files Cuewand writes here: cuewand.log, cuewand.previous.log,
cuewand_session.json (the code and clock, for restarts),
cuewand_rehearsals.json, cuewand_selftest.txt and .log, and cloudflared.exe
if you use the internet link.


What has been tried, and what has not
-------------------------------------
Tried: real PowerPoint 16 on Windows 11 by one presenter. Versions 1.3 to
1.6: connecting, notes on every slide and pictures made ahead worked.
Version 2.1, "Test Cuewand.bat" on a 26-slide deck with large GIFs: no press
ever counted twice, and both safeguards held. It also showed two things
2.2 changed, which are not yet confirmed on that computer:
- Cuewand's own re-reading of the speaker notes during the show kept
  PowerPoint busy for about four seconds each time, so a press could wait
  that long. 2.2 no longer reads notes during the show.
- After some slides come up, PowerPoint does not answer for about three
  seconds, and a press made while a slide is still appearing only finishes
  it. 2.2 tells the phone as soon as PowerPoint has taken a press, holds a
  quick press until the slide's transition is over, sends it once more if
  it was swallowed, and says "Nothing moved" if it still was.
Everything else since 1.6 has been run against a stand-in for PowerPoint
and in phone- and tablet-sized desktop browsers: 598 automated checks, in
the tests folder, plus an automated accessibility audit (axe-core) of every
screen. A stand-in written by the author cannot disagree with the author
about how PowerPoint behaves. "Test Cuewand.bat" is the real test: run it on
your deck.

Not tried at all:
- any iPhone, and any real Android phone since 1.6
- whether the silent video really keeps a given phone awake on the Same
  Wi-Fi code (the check on the phone says which method is in use; watch it
  through your first slide)
- the vibration patterns on a real phone
- the phone-hotspot route
- the internet link since one report that its code did not connect; the log
  now records what is needed to find out why
- PowerPoint's Presenter View, two screens, a deck on OneDrive with
  AutoSave, PowerPoint started as administrator
- a real screen reader: 2.3 has not yet passed the release gate below.
- PowerPoint sections and [click] notes on a real deck (the stand-in reads
  them the way PowerPoint documents them)


Release gate: a real screen reader
----------------------------------
Automated audits cannot hear a page. No version is finished until someone
has done all of this on a real phone, with VoiceOver on an iPhone and with
TalkBack on an Android phone, and written down the phone, its system
version and the date:
1. Next and Back are read with the time in minutes; a double tap presses
   once; on a slide with steps, the step's words are read once.
2. A slide change is announced once, not twice.
3. The Menu, Setup and Slides can each be reached and closed, and focus
   comes back to where it was.
4. The search field can be typed in, and a found slide opened.
5. Voice Access ("tap Next") and Switch Access press Next once.
2.3 has not been through this yet.


Options
-------
python cuewand.py --demo        a built-in deck, no PowerPoint needed
python cuewand.py --selftest    what "Test Cuewand.bat" runs (--presses 500 for more)
python cuewand.py --prepare     what "Get the internet link ready.bat" runs
python cuewand.py --internet    turn the internet link on at start
python cuewand.py --new-codes   forget the saved session
python cuewand.py --port 9000   use another port
python cuewand.py --no-browser  do not open the pairing page

python tests/run_all.py        the automated checks (any computer; the two
                                browser files need Playwright)

Credits
-------
Made by Tomer Yona: www.tomeryona.com, github.com/TomerIL.
Built with Claude, Anthropic's AI model.
The logo and its icons are in the logo folder.
The pairing codes are drawn by segno (BSD licence, by Lars Heuer), which
travels in the _vendor folder. Cuewand installs pywin32 (Python Software
Foundation licence) from PyPI, and downloads cloudflared (Apache 2.0
licence) from Cloudflare only when you ask for the internet link; neither
is included here.
Cuewand is not affiliated with or endorsed by Microsoft, Apple, Google or
Cloudflare. PowerPoint and Windows are trademarks of Microsoft; the other
product names are trademarks of their owners.
