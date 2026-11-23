# Changelog

All notable changes to **CZN Auto+** are documented in this file.

CZN Auto+ is automation for the Global PC client of Chaos Zero Nightmare. It is built on [steve1316/ok-czn-english](https://github.com/steve1316/ok-czn-english), which started as a fork of [baoxin1100/ok-kes](https://github.com/baoxin1100/ok-kes). Thanks to both.

The newest changes come first. Each section is the day a change reached the project, written as `YYYY-MM-DD`, and opens with a one-line summary, then lists what you need to do, what is new, changed and fixed, what came in from steve's version, and known issues when there are any. The layout is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has no version numbers yet.

---

## 2026-11-23

Chaos now walks itself from the Lobby to The Blue Pot, the fights the bot plays itself plan kills, Dream Park buys Another Happy Day while Happiness lags, and the bot's fallback presses leave a run's Escape alone.

### New

- **Chaos Manifestation:** started on the Lobby, the Chaos hub, the Chaos Manifestation map or the prompt to resume a run still open, Chaos now walks itself to The Blue Pot's Team Formation and starts. On the resume prompt it presses only Enter, never Cancel or Escape.
- **Dream Park:** while Happiness lags its Rank target the most, Daily buys levels of the park skill Another Happy Day with the park's profit, under the same price rule as AI Automation.
- **App and settings:** the bot keeps a record of every fight it plays itself (what it saw, what it played and how the fight ended) in the `data` folder, two files of about 8 MB at most, and remembers there how hard each combatant hits, so the first fights of a run can already plan a kill.
- **Spending safety:** the bot's fallback presses now leave a run's Escape alone, which abandons the run. An Enter that may be that Escape is not pressed, a frozen Chaos or Sortie screen showing Escape gets no random tap, a dialog that would escape a run nobody asked to leave is cancelled and the run stopped, and Daily and the Chaos walk stop before a press on Escape or Retreat.

### Changed

- **Fights:** in the fights the bot plays itself (Sortie, and Chaos and Story fights where the game's Auto is locked), an enemy that a sure attack can kill is finished first, before buffs. A card that hits the enemy you pick is aimed at the enemy it can finish, and damage that lands on a random enemy is counted on a kill only when one enemy is left.
- **Fights:** the bot no longer spends Action Points on a card that would do nothing, and plays Upgrade, shield and heal cards only when the fight needs them.
- **Fights:** each enemy's HP and action counter are read off a closer look, enemies that already acted this turn are still read, and round scenery that looks like the targeting reticle is ignored.
- **Chaos Manifestation:** Chaos opens the team page on every layer, as Sortie does, so later layers play with the current deck and team instead of the first layer's.
- **Chaos Manifestation** and **Sortie:** an Epiphany goes on a card from your "Cards to Epiphany" list when one is offered, or else on the strongest card that has none yet. When every card already carries one, or the deck has not been read, only a listed card takes it.
- **Chaos Manifestation**, **Sortie** and **Story:** after a Confirm, Continue, Leave, Next, Settlement or tap-the-screen tap, the bot moves on as soon as the caption leaves the screen, never later than before. Taps that buy, remove or equip keep the full wait.
- **Dream Park:** Daily finds AI Automation even when its row reads with a wider bullet, drags the facilities list again each time it opens, and moves on from a ride upgrade as soon as the ride's level reads risen.

### Fixed

- **Chaos Manifestation:** the card reward skip is confirmed when a card behind its dialog reads Crystallization, Retreat or Elimination, instead of stopping the run.
- **Chaos Manifestation:** the next run no longer carries on the last run's fight or its shop's equipment buying when it reaches the same floor and node, and every task starts with an empty deck.
- **Daily:** a faded Lobby is woken for the daily chores even when its character's speech bubble shows.

### Known issues

- **Chaos Manifestation:** the walk from the Lobby goes only to The Blue Pot, and stops when the map does not show it.

## 2026-11-22

Daily claims the attendance reward, and Dream Park takes its earned Rank Ups, builds Special Guest and upgrades its AI Automation skill.

### New

- **Daily:** claims today's card on the daily attendance popup, then closes it.
- **Dream Park:** once a visit, Daily upgrades the park skill AI Automation one level at a time while a level costs no more than the profit and no more than what the park earns in the 10 minutes of offline time the level adds, so it pays for itself by the next visit. No other skill is pressed.
- **Dream Park:** when the ride Daily wants sits further down the facilities list, it drags the list a short way, a few times a visit at most, so rides such as Special Guest get built.

### Changed

- **Dream Park:** when the emotion furthest behind has no ride to upgrade in view, Daily upgrades a ride of the next emotion behind instead of stopping the upgrades.
- **Dream Park:** while an earned Rank Up is still to be taken, the profit is kept for the new ride the next Rank brings rather than spent on the cheapest rides, and the Manage panel is visited at most once for each Rank target.
- **Spending safety:** Dream Park stops the visit when any line of the facilities list reads a word for Crystals, other account currency, real money or a purchase.

### Fixed

- **Dream Park:** an earned Rank Up is taken even when the Manage panel reads a slash in the emotion values as a 1.
- **Dream Park:** Daily closes the Profit Report the park opens on after time away, and skips a story a Rank Up starts, with "Do not show" ticked.
- **Daily:** the Lobby's Menu is pressed on a blank screen only when that screen is the faded Lobby.
- **Story:** "Do not show" is ticked on the smaller story skip dialog too, and a line of dialogue showing under that dialog no longer stops Story.

### From steve's version

- **Fights:** a turn whose hand counter keeps reading empty after the deal is ended instead of waited on.
- **Chaos Manifestation** and **Sortie:** every pin in an event's scene, such as an unopened chest or a Shattered Memory, is tapped before an option is picked.

## 2026-11-21

A new Daily task with a Nightmare Dream Park visit, Story plays Battle Missions and hands Chaos stages to Chaos, Chaos plays its own fights until the game's Auto unlocks, and more stops that keep your account safe.

### What you need to do

- **App and settings:** set Game Language to the language your game shows. Chaos, Sortie and Story now stop at the start with a message naming the value to set when it does not match.
- **Chaos Manifestation:** you no longer need the game's auto-battle on before Captain Lv 30, where it unlocks. Keep shortcut key display and auto-story on in the game's settings.

### New

- **Daily:** a new Daily task. Start it on the Lobby: it closes the entry popups, claims all mail and stops back on the Lobby. It wakes a faded Lobby, never presses mail deletion, the Shop, a purchase, Crystals or Rescue, and presses nothing on a screen it does not know.
- **Dream Park:** while Nightmare Dream Park runs, Daily visits it: it takes earned Rank Ups, builds newly unlocked rides, upgrades the rides of the emotion furthest behind its Rank target and claims the park's achievements. It spends only the park's own profit, and presses a row only when its price reads as a plain park number. When the event is not running, Daily skips the park.
- **Chaos Manifestation:** while the game's Auto is still locked (it unlocks at Captain Lv 30), Chaos plays its fights itself with Sortie's card picking, and stops the run when a locked fight makes no progress for 3 minutes.
- **Chaos Manifestation:** with "Claim Additional Loot with Loot Certification Cards" on, Chaos claims the final Settlement's Additional Loot with a card before it leaves, skips the claim when the counter reads 0/4 and keeps the setting on. It stops the run if the loot question keeps coming back.
- **Story:** from the Story hub, Story opens Battle Missions and plays the chapter's open NORMAL missions left to right on the game's Auto, turning on Auto in their fights.
- **Story:** when Story reaches a chapter's Chaos stage with a full team, it hands the stage to the Chaos task and takes the chapter back after the run. For that run, re-observing, Loot Certification Cards, Breakdown treatment, Zero System merges and save deletion stay off, whatever your Chaos settings say.
- **Spending safety:** Chaos, Sortie, Story and Daily stop on a Rescue screen or dialog without pressing anything, so pulls and their records stay your choice.
- **Tutorial:** while the tutorial's Skip Tutorial button shows, every mode refuses any tap on it and stops the run. Daily stops before it presses anything there.

### Changed

- **Chaos Manifestation:** a card removal takes Basic cards and never a card your build preset pinned, instead of any card on one combatant's row, unique ones included.
- **Story:** "Do not show" is ticked on the story skip dialog and on Battle Prep before they are confirmed, and the skip dialog's story summary no longer stops Story on a word that sounds like spending.
- **Story:** Story stops on the Lobby, on a screen that has not changed for 5 minutes, and when it reaches a Chaos stage again that the last Chaos run did not clear.

### Fixed

- **Chaos Manifestation:** Chaos enters at the current difficulty on the Chaos Manifestation Entry Guide, leaving its "Do not show" box to you, and closes the Exploration record notice after a run.
- **Chaos Manifestation:** things on screen that only look like event options, such as the magnifier or the Exploration record card, are no longer taken for one.
- **Chaos Manifestation** and **Sortie:** started on the Lobby, they say in English why they stopped and what to open.
- **Chaos Manifestation:** a dice result is no longer taken as failed while its caption is still blank.

### Known issues

- **Story:** Battle Missions stops when no open mission is left, at a lock, at a card that is not B1 to B6 (such as the Promotion Mission), at the growth tutorial, on a list not on its NORMAL tab, and after a mission's one retry.
- **Daily:** Daily stops, pressing nothing, on any screen it does not know for 30 seconds.

## 2026-11-20

CZN Auto+ starts: the bot refuses dialogs that spend account currency, delete or retreat unasked, stops a frozen run, and starts with every save kept and Breakdown treatment off.

### What you need to do

- **App and settings:** saved settings are kept. If yours come from steve's version, check "Treat Breakdown" (it now starts off) and "Delete Saves Worth This Many TB or Less" (it now starts at 0, which keeps every save).
- **App and settings:** there is no installer yet. Run the app from source, as the README describes.

### New

- **Spending safety:** a centred Confirm on a dialog that would spend Crystals, Aether or other account currency, pay real money, buy something not priced in Credits, delete something nobody asked to delete or retreat from a run nobody asked to leave is not confirmed: the bot presses its Cancel when one reads, otherwise nothing, and the run stops with a message. Credits inside a run stay allowed, for the shop, card removal and the like.
- **Spending safety:** in Chaos and Sortie, the bot no longer taps at random on a frozen screen that can spend or discard anything.
- **Chaos Manifestation** and **Sortie:** a run whose screen has not changed for 5 minutes stops with a message instead of looping until someone looks.
- **Chaos Manifestation:** with "Treat Breakdown" off, a run that reaches the Epione Center with a combatant to treat stops there instead of paying.

### Changed

- **App and settings:** the app is now called CZN Auto+ and credits steve1316 and baoxin1100.
