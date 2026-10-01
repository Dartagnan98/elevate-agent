"""Elevation drip campaign templates.

The campaigns, segments, playbooks and video scripts shipped with the Leads
pack. ``elevate_cli.drips_db`` seeds them into the operational store on
first use and exposes them as a template library the dashboard can install
from again. Everything here is data: an install can rename, re-time or
rewrite any of it, switch campaigns off, or ignore the library and build its
own campaigns from scratch.

Placeholders inside copy use square brackets exactly as the Elevation PDFs
do: ``[First Name]``, ``[Your Name]``, ``[Brokerage]``, ``[Area]`` and so on.
``drips_db.render_text`` fills the ones it knows (first name, agent name,
brokerage, phone) and leaves the rest for the agent to swap in.

Video slots reference ``drip_videos.slug``. A step whose ``video`` is set
renders ``[Insert video: <name>]`` with the recorded link once the realtor
has filled it in on the Videos tab.

Layering rules (from the Elevation "How the campaigns layer" lesson):

* Six segments, one question: when. New / Hot / Warm / Lukewarm / Long-Term
  / Bad Number, plus SOI for past clients and referral sources.
* One nurture campaign at a time. Moving the segment ends the old campaign
  and starts the new one the same day.
* A reply never stops a campaign; only a segment move does.
* Never two touches on the same day. The Buyer Course runs on days
  3, 5, 7, 11, 13, 16, 18, 22, 24 and the Seller Course on days
  6, 8, 12, 17, 19, 23, 26 so they miss every nurture day.
"""

from __future__ import annotations

from typing import Any

TEMPLATE_VERSION = 1

# ─── Segments ──────────────────────────────────────────────────────────

SEGMENTS: list[dict[str, Any]] = [
    {
        "key": "new",
        "label": "New",
        "window_label": "Day 1 to 14",
        "description": "A brand new lead who has not told you anything yet. Runs The First 14 Days, then day 15 files them by timeline.",
        "color": "#6B8EF2",
    },
    {
        "key": "hot",
        "label": "Hot",
        "window_label": "0 to 30 days",
        "description": "Ready to buy or sell now. No drip: hot sheet every morning, a personal touch every day, a seat on your Top 25.",
        "color": "#E05A4C",
    },
    {
        "key": "warm",
        "label": "Warm",
        "window_label": "30 to 90 days",
        "description": "You have spoken, they are real, and they are not ready this week. Warm Nurture keeps you in the room.",
        "color": "#E8933C",
    },
    {
        "key": "lukewarm",
        "label": "Lukewarm",
        "window_label": "90 to 180 days",
        "description": "Three to six months out, or a new lead who never replied. Lukewarm Nurture stays useful while they take their time.",
        "color": "#D9B341",
    },
    {
        "key": "long_term",
        "label": "Long-Term",
        "window_label": "6 months+ or quiet",
        "description": "Six months or more out, or went quiet. Long-Term Nurture is one useful touch about every six weeks, all year.",
        "color": "#5BA8A0",
    },
    {
        "key": "bad_number",
        "label": "Bad Number",
        "window_label": "Any day the phone stops working",
        "description": "The number bounced, the voicemail is full, or they asked for email only. Email carries the relationship until a number or a timeline shows up.",
        "color": "#8A8F98",
    },
    {
        "key": "soi",
        "label": "SOI / Past Clients",
        "window_label": "60 to 90 day check-ins",
        "description": "Past clients, referral sources and your sphere. The Raving Fan Club rhythm, not a timeline campaign.",
        "color": "#9B6BD6",
    },
]

# ─── Video script library ──────────────────────────────────────────────

VIDEOS: list[dict[str, Any]] = [
    {
        "slug": "market-insight",
        "name": "Market Insight",
        "length_label": "60 to 90 seconds",
        "used_in": "Warm day 30 (optional) · Lukewarm day 45 · Long-Term day 90",
        "script": "Hi [First Name], it is [Your Name]. I wanted to give you a quick snapshot of what I am seeing in the market right now, because a lot of buyers are trying to make sense of what they see online.\n\nDepending on the area and price point, some homes are sitting a long while and taking price reductions, and some are moving quickly, especially when they are priced right. The key is knowing where the opportunities are, and that is what I help my clients stay ahead of, by sharing sold prices and trends so when a great one pops up, we can make the best choice for you.\n\nAs you browse, watch three things: how long homes stay on the market, what similar homes actually sell for, and which ones buyers pass on.\n\nWhat have you noticed in [Area] so far?\n\nRe-record it every quarter, or when the market turns, and swap the one link everywhere it is used.",
    },
    {
        "slug": "exploratory-tour",
        "name": "Exploratory Tour",
        "length_label": "45 to 60 seconds",
        "used_in": "Warm day 14 · Lukewarm day 60 · Long-Term day 45 · Buyer Course lesson 3",
        "script": "Hi [First Name], it is [Your Name]! I wanted to personally invite you on an exploratory home tour. This is hands down the best way to learn the market and feel confident when the right home comes along.\n\nI often get told \"we are not looking to buy just yet,\" which is great, because this tour is all about exploring different areas, comparing what your budget gets you in different neighbourhoods, and getting real market knowledge that helps you make the best decision when the time is right.\n\nI am going to send you a text right after this. Does an evening or a weekend work better for you?\n\nFilm it at a showing or in front of a listing. It is the tour you are selling, so let them see one.",
    },
    {
        "slug": "how-i-work",
        "name": "How I Work",
        "length_label": "45 to 60 seconds",
        "used_in": "Lukewarm day 180 · Long-Term day 180",
        "script": "Hi [First Name], it is [Your Name]. I wanted to share a bit about how we work, because it is a little different.\n\nA lot of agents work solo, which can mean delays or missed opportunities. We have set things up so you always have someone available, whether that is booking a showing or handling a negotiation. Showings never slow you down, the strategy gets my full attention, and you are never wondering what the next step is.\n\nSo many of my clients have said to me after, \"I can't believe how easy that was!\"\n\nWhat matters most to you in the person helping you with your move?\n\nWorking solo? Say \"I\" instead of \"we\" and keep the rest. Film it somewhere that looks like your working day.",
    },
    {
        "slug": "client-story",
        "name": "Client Story",
        "length_label": "45 to 60 seconds",
        "used_in": "Warm day 50 (optional) · Lukewarm day 120 · Long-Term day 225",
        "script": "Hi [First Name], buying a home can feel overwhelming, but you do not have to do it alone. I wanted to share a quick story about [client names], who were in the exact same position as you. Excited to buy, but unsure about the process.\n\nWe set up a personalized home search so they were not wasting time scrolling. We took them on exploratory tours so they could feel confident in their options. And we built a negotiation strategy that got them a great price and the dates they needed. The result? They found a home they love, and it felt easy.\n\nEvery buyer's journey is different, which is why we tailor it to you. What would it mean for you to be in your own place by [season]?\n\nOne real client, named only with their permission. Even better, a clip of them saying it themselves.",
    },
    {
        "slug": "course-welcome",
        "name": "Course Welcome",
        "length_label": "30 to 45 seconds",
        "used_in": "Buyer Course, lesson 1",
        "script": "Welcome! Whether you are a first-time buyer or you have bought before, I am so glad you are here.\n\nThe truth is, the buying process has changed a lot, and this quick video series walks you through the key steps, from your search and showings to financing and possession day. Each one builds on the last, so watch them in order and set aside a few minutes every couple of days. Think of it as your crash course in becoming a confident, informed homeowner.\n\nSo let me ask you, what is the one part of buying you most want to feel sure about?\n\nSmile at the start. This is the first lesson, and it sets the tone for all nine.",
    },
    {
        "slug": "search-setup",
        "name": "Search Setup",
        "length_label": "45 to 60 seconds",
        "used_in": "Buyer Course, lesson 2",
        "script": "The very first step is a quick strategy session, either on Zoom or in person. I ask you a few key questions and walk you through my VIP Buyer Package, which is your go-to for timelines, terms and what to expect.\n\nThen I set you up with your own MLS search. Think of it as a backstage pass: the active listings and the sold data. Watching what homes list for, and what they actually sell for, builds your market IQ fast. This is not about rushing. It is about getting clarity before we ever step into a house.\n\nDoes a weekday or the weekend work better for your strategy session?\n\nScreen-record a quick scroll through a sold search if your tool allows it. Seeing it beats hearing about it.",
    },
    {
        "slug": "your-numbers",
        "name": "Your Numbers",
        "length_label": "60 to 90 seconds",
        "used_in": "Buyer Course, lesson 4",
        "script": "Financing can feel overwhelming, so let me break it down.\n\nGet your pre-approval before you fall in love with a home, so you know your real budget. Beyond your down payment, plan for closing costs like your inspection, your legal fees and property transfer tax if it applies.\n\nAnd getting pre-approved is one thing, getting the right support is another. A great mortgage broker sends your file to the lenders that fit you best, because yes, they all have different products. When your broker and I are on the same timeline, everything goes from good to great.\n\nDo you already have a broker you love, or should I connect you with one of mine?\n\nBetter yet, record this one with your favourite mortgage broker. Two faces, one message.",
    },
    {
        "slug": "showings",
        "name": "Showings",
        "length_label": "45 to 60 seconds",
        "used_in": "Buyer Course, lesson 5",
        "script": "Once we have narrowed down a few homes you like, we start booking showings.\n\nWhen you walk in, look past the paint and the staging. The things that matter most are the ones you cannot change easily: the location, the lot, the layout and the light. Then check the big-ticket items like the roof, the windows and the furnace, and how old they are.\n\nAfter every showing, ask yourself one thing: does this one beat the last one? Compare homes that way, and when the right one comes along, you will recognise it instantly.\n\nWhich home have you seen so far that you keep thinking about?\n\nFilm it walking through a listing. Point at the things you are talking about.",
    },
    {
        "slug": "offer-strategy",
        "name": "Offer Strategy",
        "length_label": "60 to 90 seconds",
        "used_in": "Buyer Course, lesson 6",
        "script": "Once you have found the one, we schedule a second showing and take a deep dive. This is where I step in directly, reviewing the property with a strategic lens.\n\nBefore we write anything, I ask you what success actually looks like for you. Price? Timing? Conditions? Then we look at the market, the pricing history and your goals, and build an offer that protects you and stands out.\n\nYou will never be pressured. I share the facts, and you make the call.\n\nWhat matters most to you when it comes time to write an offer?\n\nTalk to the camera like you are across the table from them. No slides, no screen share.",
    },
    {
        "slug": "after-the-accepted-offer",
        "name": "After the Accepted Offer",
        "length_label": "60 to 90 seconds",
        "used_in": "Buyer Course, lesson 7",
        "script": "Congratulations! I want to give you a sneak peek of what happens after you get an accepted offer. Now that negotiations are done, we send you a checklist so everything you need is right at your fingertips and nothing gets missed.\n\nWe go through the due diligence: the inspection, your financing and the legal paperwork. We send your broker every document about the property so your financing is secured before subjects come off, and we give you home inspector suggestions and everything you need for insurance. One tip I give every client: be at the last 30 minutes of your inspection so you can ask questions.\n\nThen you decide to move forward, and we send it all to the lawyer. It sounds super simple, but there is a lot happening on the back end, and we have you covered.\n\nWhat part of this are you most wanting to understand?\n\nKeep the energy up. This is a celebration first and a process second.",
    },
    {
        "slug": "possession-day",
        "name": "Possession Day",
        "length_label": "45 to 60 seconds",
        "used_in": "Buyer Course, lesson 8",
        "script": "Possession day is the best part, and we have you covered all the way to the end.\n\nAs it gets closer, we remind you to book your appointment with the lawyer to sign the transfer papers. That is where you bring in the rest of your down payment. Book your movers or truck early. Set up your utilities before you move in. Internet always books about a week out, and we don't need you living without wifi! And forward your mail so nothing gets lost.\n\nOne big no-no: no new credit cards, loans or big purchases like cars, trailers or new furniture until you have the keys.\n\nWhat are you most excited to do first in your new place?\n\nIf you give a closing gift, show it here. It gives them something to look forward to.",
    },
    {
        "slug": "assessments-vs-appraisals",
        "name": "Assessments vs Appraisals",
        "length_label": "45 to 60 seconds",
        "used_in": "Buyer Course, lesson 9",
        "script": "These three numbers, assessment, appraisal and list price, cause a lot of confusion, so let me clear it up.\n\nYour assessment comes from BC Assessment. It is what they say the home was worth on July 1 of last year, and it is used for property taxes. It is not what the home will sell for. An appraisal is done for your lender, and it tells the bank how much they are comfortable lending. And the list price is simply what the seller is asking.\n\nThe number to actually pay attention to is what similar homes have sold for. That alone will make you a smarter buyer. Which of those three numbers has confused you the most?\n\nOutside BC? Swap in your own assessment authority and its valuation date.",
    },
    {
        "slug": "seller-welcome",
        "name": "Seller Welcome",
        "length_label": "30 to 45 seconds",
        "used_in": "Seller Course, lesson 1",
        "script": "Hi there! I am so glad you are here. I created this video series to walk you through the exact steps we take when helping our clients sell their homes.\n\nWhether this is your first time or your fifth, real estate is always changing, and I want you to have the full picture. This is not a bunch of fluff. It is the actual process we use with sellers, from the very first conversation to handing over the keys.\n\nSo grab a coffee and keep an eye on your inbox. What has you thinking about selling right now?\n\nSmile at the start. This one sets the tone for all seven.",
    },
    {
        "slug": "pre-listing-game-plan",
        "name": "Pre-Listing Game Plan",
        "length_label": "30 to 45 seconds",
        "used_in": "Seller Course, lesson 2",
        "script": "The pre-listing phase is everything. Before we even book photos, we send you our Seller Package. It shows how we market homes, what upgrades are available, and how we create urgency before your home even hits the MLS.\n\nYou also get to choose any optional add-ons, like a pre-listing clean, a pre-listing inspection or a listing video. We built it this way so you feel in control and choose what matters most to you.\n\nWhat matters most to you before your home hits the market?\n\nHold up or screen-share your actual Seller Package. Let them see it.",
    },
    {
        "slug": "home-evaluation",
        "name": "Home Evaluation",
        "length_label": "30 to 45 seconds",
        "used_in": "Seller Course, lesson 3",
        "script": "The walkthrough gives me what I need to price your home strategically. I pull similar homes in your area that recently sold and compare them one by one to yours.\n\nFrom there, I build a pricing sandwich: one home slightly nicer, one slightly less. That is how we find what buyers will realistically pay in today's market. And we make that decision together. I give you the puzzle pieces, and you choose the strategy.\n\nWhat do you love most about your home?\n\nIf you can, sketch the pricing sandwich on paper while you talk. It sticks.",
    },
    {
        "slug": "pre-launch-strategy",
        "name": "Pre-Launch Strategy",
        "length_label": "20 to 30 seconds",
        "used_in": "Seller Course, lesson 4",
        "script": "Most agents hit publish and cross their fingers. Not us.\n\nWe build momentum before launch, from picking the perfect go-live day to creating a bottleneck of buyers who are ready to see your home right away. It is all about creating demand and stacking the odds in your favour.\n\nWhen would you love to have it on the market?\n\nShort and punchy. This is the one to film with some energy.",
    },
    {
        "slug": "showings-and-feedback",
        "name": "Showings and Feedback",
        "length_label": "20 to 30 seconds",
        "used_in": "Seller Course, lesson 5",
        "script": "Once your home is on the market, I take over the coordination so you do not have to stress. I follow up with every agent for feedback.\n\nAnd if the market is slower than expected, we use that data to adjust the strategy so your home never sits stale.\n\nWhat would you want to hear from me after a showing?\n\nShow a real (anonymised) feedback summary if you send one.",
    },
    {
        "slug": "negotiation-strategy",
        "name": "Negotiation Strategy",
        "length_label": "20 to 30 seconds",
        "used_in": "Seller Course, lesson 6",
        "script": "I do not just accept the first offer that comes in. I work to bring in multiple offers and negotiate the best possible terms: not just the price, but the timelines and the subjects too.\n\nMy job is to make sure you walk away with confidence, not regrets.\n\nWhat would a win look like for you, the price or the dates?\n\nLook straight down the lens for the last line. It is a promise.",
    },
    {
        "slug": "after-the-sale",
        "name": "After the Sale",
        "length_label": "20 to 30 seconds",
        "used_in": "Seller Course, lesson 7",
        "script": "The sale might be done, but our job is not. We send over your moving checklist, help with possession prep, and make sure you feel supported all the way through to handing over the keys.\n\nThat is just how we do business: with clarity, communication and care.\n\nWhere are you hoping to land after this move?\n\nTheir answer to that question is often your next deal.",
    },
    # The First 14 Days keeps its own three new-lead videos.
    {
        "slug": "new-lead-welcome",
        "name": "Welcome (new lead)",
        "length_label": "30 to 45 seconds",
        "used_in": "The First 14 Days, day 1",
        "script": "Hi [First Name], it is [Your Name]. I just wanted to say welcome and put a face to the name. Most people start out just seeing what is out there, and that is exactly what this is for. We have helped a lot of people make a smart move by setting up the right search and keeping them clear on what is really happening in the market. So tell me, what is the one thing your next home has to have?",
    },
    {
        "slug": "new-lead-market-insight",
        "name": "Market Insight (new lead)",
        "length_label": "60 to 90 seconds",
        "used_in": "The First 14 Days, day 6",
        "script": "Hi [First Name], it is [Your Name]. Here is what I am seeing in [Area] right now. [Some homes are sitting and dropping their price, the ones priced right are going fast.] As you browse, the list price is not the thing to watch. Watch how long homes sit, what similar ones actually sell for, and which ones buyers keep passing on. That is where the opportunities are. What have you noticed so far?",
    },
    {
        "slug": "new-lead-client-story",
        "name": "Client Story (new lead)",
        "length_label": "45 to 60 seconds",
        "used_in": "The First 14 Days, day 14",
        "script": "Hi [First Name], it is [Your Name]. I wanted to tell you about [client names]. When they started they were [overwhelmed / not sure they could buy yet]. We broke it down, set up their search, and [found the right home at the right price / made the move a year sooner than they thought]. They started right where you are. What would it mean for you guys to be in your own place by [season]?",
    },
]

# ─── Campaigns ─────────────────────────────────────────────────────────
#
# Step keys: day, channel (text | email | call | task | tag), title,
# subject (email only), body, video (video slug), notes, route_to (tag steps
# only: a segment key, "done" to finish a run-once course, or "restart" to
# begin the campaign again at day 1).

_LAYER_NOTE = (
    "Layer by the conversation. Buying: add the Buyer Course. Selling: add the "
    "Seller Course. Both: add both. Start them the same day as this campaign. "
    "Their days are already set so none of them clash, and each runs once per person."
)

CAMPAIGNS: list[dict[str, Any]] = [
    {
        "slug": "first-14-days",
        "name": "The First 14 Days",
        "kind": "nurture",
        "role": "primary",
        "trigger_segment": "new",
        "defer_layers": True,
        "exit_day": 15,
        "exit_rule": "Day 15 files them: by timeline if they gave one (Hot, Warm, Lukewarm or Long-Term), Lukewarm if they never replied. A bad number on any day moves them to the Bad Number Drip.",
        "description": "The two weeks that decide whether a new lead becomes your client. Thirteen touches over fourteen days across call, text, email and video, each one ending in a question that gets them talking.",
        "source_url": "https://drive.google.com/file/d/1j1r8rDDrfZE0SSWOSl2z48cjb1nG8Hfi/view",
        "notes": "Speed first: call inside five minutes when you can. Every touch ends in one forward question, never a bare \"let me know\". Never hand them an out. The Buyer Course never runs inside these 14 days; it starts on day 15 alongside their new segment.",
        "steps": [
            {"day": 1, "channel": "call", "title": "Say hi inside five minutes", "body": "Hi [First Name], it is [Your Name] with [Brokerage]. I saw you were just looking at homes on my site and wanted to put a voice to the name :)\n\nWhat has you looking right now?", "notes": "No answer? Leave this: \"Hi [First Name], it is [Your Name] with [Brokerage]. I saw you were looking at homes in [Area] and wanted to say hi. I will text you so you have my number.\""},
            {"day": 1, "channel": "text", "title": "Right after the call", "body": "Hi [First Name]! It is [Your Name] from [Brokerage] :) Thanks for checking out homes on my site.\n\nWhich area of town are you most curious about right now?"},
            {"day": 1, "channel": "email", "title": "Welcome, with video", "subject": "Welcome, quick question about your search", "body": "Hi [First Name] :)\n\nWelcome! You can browse homes, save your favourites and get a feel for what is out there. I will check in along the way to make sure your search is actually helping you, and not just sending you noise.\n\n[Insert video: Welcome]\n\nWhat is the one thing your next home has to have?", "video": "new-lead-welcome", "notes": "Not recorded yet? Delete the video line."},
            {"day": 2, "channel": "text", "title": "Sold, not listed", "body": "Hi [First Name] :) As you are browsing, I can also send you what similar homes are actually selling for. List prices only tell you half the story.\n\nWhich area should I start with?"},
            {"day": 3, "channel": "email", "title": "A filtered search", "subject": "A more filtered way to search", "body": "Hi [First Name] :)\n\nQuick question. As you browse, does it feel like you are seeing too many homes, the right amount, or not the right ones?\n\nI feel like most buyers do better with a filtered search. You only see the homes that match what you care about, plus what the similar ones actually sold for, so you spend less time scrolling and more time comparing.\n\nWhat are the three must-haves I should build it around?"},
            {"day": 4, "channel": "call", "title": "Second call", "body": "Hi [First Name], it is [Your Name] :) I wanted to follow up on your search and make sure the homes coming through are actually the right ones.\n\nWhat have you seen so far that you liked?", "notes": "No answer? Send a voice note instead of a voicemail. Same words, thirty seconds."},
            {"day": 5, "channel": "text", "title": "What is not working", "body": "Hi [First Name] :) Quick question for you.\n\nWhat about where you are living now is not quite working anymore?"},
            {"day": 6, "channel": "email", "title": "The market, on video", "subject": "What is happening in [Area] right now", "body": "Hi [First Name] :)\n\nI recorded a short video on what I am seeing in the market right now: what is happening with prices, how buyers are handling it, and what to watch for as you look.\n\n[Insert video: Market Insight]\n\nAfter watching, what stood out to you?", "video": "new-lead-market-insight", "notes": "Not recorded yet? Tell them the three things to watch in two lines instead."},
            {"day": 7, "channel": "text", "title": "The exploratory tour", "body": "Hi [First Name] :) Photos flatten everything. Seeing a few homes in person is the fastest way to get a feel for value and layout.\n\nWe call it an exploratory tour. Not to buy, just to get clear. Does a weekday evening or a weekend morning work better for you?"},
            {"day": 9, "channel": "email", "title": "How you work", "subject": "How I support my clients", "body": "Hi [First Name] :)\n\nI wanted to share a bit about how I work. For some clients availability matters most, for others it is strategy, and for a lot of people it is just having the process feel calm and organized.\n\nSo I have set things up so showings never slow you down, the strategy and negotiating get my full attention, and you are never wondering what the next step is.\n\nWhat matters most to you when you are working with an agent?"},
            {"day": 10, "channel": "call", "title": "Third call", "body": "Hi [First Name], it is [Your Name] :) I have a couple of homes in mind I think you would like and wanted to run them by you.\n\nWhat is your timing looking like for a move?", "notes": "No answer? Voice note again. This is the call that most often gets you their timeline, so ask it straight."},
            {"day": 11, "channel": "text", "title": "Your reviews", "body": "Hi [First Name] :) If you are curious what working together is actually like, here are a few of my clients in their own words. [Review link]\n\nWhich part of buying are you most wanting to get right?"},
            {"day": 14, "channel": "email", "title": "A client story, on video", "subject": "Someone who was right where you are", "body": "Hi [First Name] :)\n\nI wanted to share one of my client stories with you, because they started exactly where you are now.\n\n[Insert video: Client Story]\n\nI would love to sit down for half an hour and build your plan: your area, your numbers and your timing. Does a weekday evening or a weekend morning work better for you?", "video": "new-lead-client-story", "notes": "One real client, named with their permission. Not recorded yet? Tell it in three sentences."},
            {"day": 15, "channel": "tag", "title": "Move the tag", "body": "Under 30 days: Hot. 30 to 90 days: Warm. 90 to 180 days: Lukewarm. Six months or more: Long-Term. No reply at all: Lukewarm. Number does not work: Bad Number. The Buyer Course starts the same day as their new segment.", "route_to": "lukewarm", "notes": "Automatic default: anyone still tagged New on day 15 moves to Lukewarm. Move them sooner the day they give you a timeline."},
        ],
    },
    {
        "slug": "hot-leads",
        "name": "Hot Leads",
        "kind": "playbook",
        "role": "primary",
        "trigger_segment": "hot",
        "description": "A hot lead does not get a drip. They get you. Hot is 0 to 30 days: daily hot sheet, a personal touch every day, a seat on your Top 25, and the Buyer or Seller Course underneath as the one thing you automate.",
        "source_url": "https://drive.google.com/file/d/1lTNWHXfhuxJsQMWQCiyJW_rmTUCEnYo1/view",
        "notes": "EVERY DAY THEY ARE HOT\n✓ Hot sheet checked, anything new sent\n✓ One personal touch made today (call, text, voice note or video)\n✓ Buyer or Seller Course drip running\n✓ This week: posted, mailed, knocked or called for them\n✓ Offer pieces in place: deposit, lawyer, inspector, possession\n\nFIND THEM A HOUSE\nPost it: tell everyone you have a buyer (community pages, your feed, a news blast). Mail it: one short letter to the complexes they like. Knock it: 10 doors each side, 10 across. Call it: the expireds, the cancelled listings, the agents who sell in that area, your Top 25.\n\nMOVE IT FORWARD\nFinancing confirmed in writing, criteria on one line (three must-haves, three nice-to-haves, two deal breakers), an exploratory tour for anyone who has not been inside enough homes, and the offer pieces decided before the right house appears.",
        "steps": [
            {"day": 1, "channel": "task", "title": "Hot Client Card", "body": "Fill in the Hot Client Card: name, timeline and move date, pre-approved for and with whom, price range, three must-haves, two deal breakers, areas and complexes they like, last showing and what they said. Put them on your Top 25.", "notes": "One card per hot lead, today."},
        ],
    },
    {
        "slug": "warm-nurture",
        "name": "Warm Nurture",
        "kind": "nurture",
        "role": "primary",
        "trigger_segment": "warm",
        "exit_day": 92,
        "exit_rule": "Day 92: a date on the calendar means Hot and a seat on your Top 25. No date means Lukewarm and its monthly rhythm.",
        "description": "The 30 to 90 day rhythm that keeps a warm lead moving toward a decision. Eleven touches over roughly three months, mixed across text, email, voice note and video, each one ending in a question that moves them one step closer.",
        "source_url": "https://drive.google.com/file/d/1Pbluq1sTNGMd1sxpsmeGKrcAVDSNxFZJ/view",
        "notes": _LAYER_NOTE + "\n\nVideo and voice notes: every touch works as plain text. Record days 9 and 40 as voice notes first. Then add the day 14 tour video, Market Insight on day 30 and Client Story on day 50.",
        "steps": [
            {"day": 1, "channel": "text", "title": "Open the loop", "body": "Hi [First Name] :)\n\nThought I would circle back. It has been a few weeks since we talked about [area or home type].\n\nWhat has changed on your end since then, the timing or what you are looking for?", "notes": "Video option: same words, 20 seconds, camera on."},
            {"day": 4, "channel": "email", "title": "Make it about their street", "subject": "What actually sold in [Area] this month", "body": "Hi [First Name] :)\n\nThree homes sold in [Area] in the last 30 days. [Address 1] went for [price] in [days] days, [Address 2] for [price], and [Address 3] for [price].\n\nI feel like sold prices tell you way more than list prices do. List price is what someone hoped for. Sold is what the market actually paid.\n\nWhich of those three is closest to what you had in mind?"},
            {"day": 9, "channel": "text", "title": "Three homes, picked by hand", "body": "Hi [First Name], I picked three out of everything that came up this week. Not the whole list, just the three I would actually walk you through. [Links]\n\nWhich one would you want to see inside first?", "notes": "Voice note option: record the same thirty seconds. Say why you picked each one."},
            {"day": 14, "channel": "email", "title": "The exploratory tour", "subject": "The fastest way to get clear on your search", "body": "Hi [First Name] :)\n\nPhotos flatten everything. Rooms look bigger, yards look level, and the highway is never in the picture.\n\nSo before anyone makes an offer, we do an exploratory tour. Four or five homes across your range, in a couple of different areas. Not to buy. Just so you can feel what your money actually gets you. It is the thing my clients say helped the most.\n\n[Insert video: Exploratory Tour]\n\nDoes a weekday evening or a weekend morning work better for you?", "video": "exploratory-tour"},
            {"day": 21, "channel": "text", "title": "What has shifted", "body": "Hi [First Name], now that you have seen a bunch of homes, what has moved on your list?\n\nThe garage, the area, the price, the timing. Something always shifts around this point.\n\nWhich one is it for you?"},
            {"day": 30, "channel": "email", "title": "What their money gets now", "subject": "Your price range, a month later", "body": "Hi [First Name] :)\n\nQuick market note for [price range] in [Area]. There are [number] homes available right now, against [number] a month ago, and they are taking about [days] days to sell.\n\nWhat that means for you: [one sentence about more choice, less competition, or the opposite].\n\nDoes that change your timing at all, or are you still aiming at [their timeline]?", "video": "market-insight", "notes": "Video option: add Market Insight under the numbers."},
            {"day": 40, "channel": "text", "title": "The one thing in the way", "body": "Hi [First Name] :)\n\nBeing straight with you. Every buyer I work with has one thing sitting in the way. Usually it is the money, the right home not existing yet, or something that has to happen first.\n\nWhich of the three is it for you?", "notes": "Voice note option: better spoken. A hard question in a warm voice reads as care."},
            {"day": 50, "channel": "email", "title": "Somebody who felt the same", "subject": "A buyer who felt exactly like this", "body": "Hi [First Name] :)\n\nI worked with a buyer last year who was at this exact point. They were not unsure about buying. They were unsure about whether they were making a smart call.\n\nWe slowed down, got clear on the numbers, and looked at three areas instead of one. They bought in [month] and told me the only thing they would change is starting the tours sooner.\n\nWhat would make you feel like you were making a smart call here?", "video": "client-story", "notes": "Video option: swap the story for Client Story from the Video Script Library."},
            {"day": 60, "channel": "text", "title": "One specific home", "body": "Hi [First Name], [Address] came up today and it is the closest thing to your list I have seen in weeks. [Link]\n\nIs it worth a look this week, or has something on your list changed?"},
            {"day": 70, "channel": "email", "title": "What another year looks like", "subject": "A real question for you", "body": "Hi [First Name] :)\n\nWe have been at this a few months now, so let me ask you the question I ask everybody at this point.\n\nIf nothing changed, and a year from now you were still in the same place, paying the same rent or living with the same [their reason], how would that sit with you?\n\nWhat would that mean for you guys?"},
            {"day": 85, "channel": "email", "title": "Coffee and a plan", "subject": "Coffee this week?", "body": "Hi [First Name] :)\n\nI would love to sit down for half an hour, on me. We narrow the criteria down properly, look at what the market has actually done since we started, and build the plan for when you move.\n\nYou leave knowing exactly what the next step is and what it costs.\n\nDoes a weekday morning or an afternoon work better for you?"},
            {"day": 92, "channel": "tag", "title": "Move the tag", "body": "Date on the calendar: Hot. No date: Lukewarm.", "route_to": "lukewarm", "notes": "Automatic default: anyone still Warm a week after the coffee ask moves to Lukewarm. Move them to Hot yourself the day they set a date."},
        ],
    },
    {
        "slug": "lukewarm-nurture",
        "name": "Lukewarm Nurture",
        "kind": "nurture",
        "role": "primary",
        "trigger_segment": "lukewarm",
        "exit_day": 187,
        "exit_rule": "Day 187: a new timeline moves them to Warm or Hot. None means Long-Term Nurture.",
        "description": "The 90 to 180 day rhythm for someone taking their time, and for every new lead who never replied in their first 14 days. Thirteen touches over six months: a monthly email, a call every six weeks and the odd text.",
        "source_url": "https://drive.google.com/file/d/1dhLpssZq9XbGETEFt5NFpcAcWwi0-hYK/view",
        "notes": _LAYER_NOTE,
        "steps": [
            {"day": 1, "channel": "email", "title": "A quick check-in", "subject": "A quick check-in from me :)", "body": "Hi [First Name] :)\n\nTaking your time with a move is honestly the best position to be in. It is how you make the right call instead of a rushed one, and I am glad to be the one keeping an eye out for you while you do.\n\nOver the next few months I will send you things worth knowing: what is selling in your area, a few tools I love, and the odd question so I can keep an eye out for the right fit.\n\nWhat would need to happen for the timing to feel right for you?"},
            {"day": 14, "channel": "text", "title": "Anything catch your eye?", "body": "Hi [First Name] :) Send me anything online that made you think ooh, maybe, and I will give you the real story on price and resale.\n\nWhat has caught your eye lately?"},
            {"day": 30, "channel": "call", "title": "First check-in call", "body": "Hi [First Name], it is [Your Name] :) You popped into my head and I wanted to check in properly.\n\nWhat has changed on your end since you first started looking?", "notes": "No answer? Send the same words as a voice note, thirty seconds. For a lead you have never spoken to, this is the first real hello, so keep it light."},
            {"day": 45, "channel": "email", "title": "A second opinion", "subject": "Still keeping an eye on the market?", "body": "Hi [First Name] :)\n\nBeing able to watch the market, explore different areas and gather all the puzzle pieces before you jump in is such a smart move.\n\nIf you are browsing listings or comparing neighbourhoods, send me anything you want a second opinion on: pricing, resale value, or whether something is too good to be true. You will get honest insight from me.\n\n[Insert video: Market Insight]\n\nWhich area are you keeping the closest eye on?", "video": "market-insight"},
            {"day": 60, "channel": "email", "title": "Step inside a few homes", "subject": "Want to step inside a few homes?", "body": "Hi [First Name] :)\n\nSometimes the best way to get clarity is to step inside a few homes and start picturing what life could look like.\n\nI call it an exploratory tour: a casual walk-through of homes in different areas and price points. You do not have to be ready to buy. It is just a way to compare your options in real life.\n\n[Insert video: Exploratory Tour]\n\nDoes an evening or a weekend work better for you?", "video": "exploratory-tour"},
            {"day": 75, "channel": "call", "title": "How is everyone feeling?", "body": "Hi [First Name], it is [Your Name] :) I was thinking about you guys. Everyone processes a move a bit differently, especially when kids are involved.\n\nHow is everyone at home feeling about the idea of moving?", "notes": "No answer? Voice note, same words. This one lands warmer spoken than typed."},
            {"day": 90, "channel": "email", "title": "A tool worth knowing", "subject": "A tool I think every buyer should know about", "body": "Hi [First Name] :)\n\nHere is one of my favourite tools: the property map portals. They let you look up lot lines and zoning, legal descriptions, and nearby services and land use, all before you make a decision.\n\nHere are the ones for my areas: [your map portal links]\n\nIs there a street or a neighbourhood you want me to look up for you?"},
            {"day": 105, "channel": "text", "title": "The weekend question", "body": "Hi [First Name] :) Random question, but it helps me more than you would think. Knowing what you love helps me suggest areas that fit you, not just your budget.\n\nWhat is your ideal way to spend a weekend?"},
            {"day": 120, "channel": "email", "title": "The next chapter", "subject": "What kind of lifestyle are you hoping for with your next move?", "body": "Hi [First Name] :)\n\nWhen people are exploring a move, it is rarely just about the home. It is about the lifestyle they are hoping to step into.\n\nWalkable streets, space to garden, a shorter commute, room for the kids to run around, or a quiet place to retire. When I know what you are aiming for, I can keep an eye out for the areas and homes that fit the bigger picture.\n\n[Insert video: Client Story]\n\nWhat does your next chapter look like?", "video": "client-story"},
            {"day": 135, "channel": "call", "title": "Timing check", "body": "Hi [First Name], it is [Your Name] :) Last time we talked you were thinking [their timeline], and I wanted to check in on your plans.\n\nIs that still the plan, or has it moved?", "notes": "This is the call that most often moves someone to Warm. Ask it straight. No timeline on the card yet? Open with \"I wanted to check in on your plans\" and ask when they are hoping to make a move."},
            {"day": 150, "channel": "email", "title": "What actually sold", "subject": "What homes near you actually sold for", "body": "Hi [First Name] :)\n\nMost people only see list prices, and those rarely tell the full story. What homes actually sell for is how you understand the market and spot the patterns.\n\nHere are three recent sales in [Area]: [Address 1] sold for [price], [Address 2] for [price] and [Address 3] for [price].\n\nWhich area should I pull next for you?"},
            {"day": 165, "channel": "text", "title": "Just popped in my head", "body": "Hi [First Name]! You just popped in my head.\n\nHas anything shifted with your timing lately?"},
            {"day": 180, "channel": "email", "title": "What is next for you", "subject": "Just checking in, what is next for you?", "body": "Hi [First Name] :)\n\nIt has been about six months since we first connected about your move, so I wanted to check in properly. Here is what I can do for you next:\n\n• Set up an exploratory tour so you can get a feel for different areas\n• Pull market stats or property info on anything that catches your eye\n• Sit down and map out your timeline, even if it is a year away\n\n[Insert video: How I Work]\n\nWhich of those would help you most right now?", "video": "how-i-work"},
            {"day": 187, "channel": "tag", "title": "Move the tag", "body": "New timeline: Warm or Hot. None: Long-Term Nurture.", "route_to": "long_term", "notes": "Automatic default: anyone still Lukewarm a week after the day 180 email moves to Long-Term."},
        ],
    },
    {
        "slug": "long-term-nurture",
        "name": "Long-Term Nurture",
        "kind": "nurture",
        "role": "primary",
        "trigger_segment": "long_term",
        "exit_day": 367,
        "exit_rule": "Day 367: a timeline moves them to Lukewarm, Warm or Hot. None restarts the year at day 1 with fresh market numbers.",
        "description": "The year-long rhythm for someone six months or more out, or who went quiet. Nine touches over a year, about one every six weeks, then it starts again so you are never gone from their inbox for long.",
        "source_url": "https://drive.google.com/file/d/1gDp7Cqc2sj0f89L5gXKeeRtAc8weku4-/view",
        "notes": _LAYER_NOTE + "\n\nOpted out or bought elsewhere? Take them off every campaign that day and mark them do not contact. Long-Term is for people with a future, not people who said no.",
        "steps": [
            {"day": 1, "channel": "email", "title": "Still here", "subject": "Still keeping an eye out for you", "body": "Hi [First Name] :)\n\nIt has been a little while since we first connected, and I wanted you to know I am still keeping an eye out for you. Whether your move is six months away or a couple of years out, my goal is to be the person you can ask anything along the way.\n\nSo every few weeks you will get something useful from me: what the market is doing, a few tools I love, and the odd question.\n\nIs your move more like six months away, a year, or further out than that?"},
            {"day": 45, "channel": "email", "title": "Explore at your own pace", "subject": "What if you could explore without needing to be ready?", "body": "Hi [First Name] :)\n\nOne of my favourite parts of how I work is something I call the exploratory tour. It is a way to visit a few homes and neighbourhoods without needing to be ready to buy.\n\nIt is not about jumping in too fast. It is about learning the market in person, at your own pace, so you know exactly what you want when the time comes.\n\n[Insert video: Exploratory Tour]\n\nWhich neighbourhood would you want to see first?", "video": "exploratory-tour"},
            {"day": 90, "channel": "email", "title": "The market, this season", "subject": "Curious what is happening in the market right now?", "body": "Hi [First Name] :)\n\nEven if your move is a ways off, it helps to know what the market is doing. Here is the quick version for [Area] this [season]: [average price], [how fast homes are selling], and [what buyers and sellers are doing right now].\n\n[Insert video: Market Insight]\n\nWhich area should I keep you posted on?", "video": "market-insight", "notes": "Swap the season line every quarter."},
            {"day": 135, "channel": "email", "title": "A quick question", "subject": "Quick question for you", "body": "Hi [First Name] :)\n\nAs you think about a move, I would love to know more about what matters to you. What does the dream look like after the move? More time in the yard, closer to the lake, room for family to visit?\n\nWhen I know what you are aiming for, I can send you things that actually fit, not just listings that miss the mark.\n\nWhat would a perfect day look like for you after your move?"},
            {"day": 180, "channel": "email", "title": "How I work", "subject": "Why working with me feels different", "body": "Hi [First Name] :)\n\nI wanted to share why my clients say they feel more supported, better informed and a lot less stressed when they buy or sell with me.\n\nShowings never slow you down, the strategy gets my full attention, and you are never wondering what the next step is.\n\n[Insert video: How I Work]\n\nWhat would make a move feel easy for you?", "video": "how-i-work"},
            {"day": 225, "channel": "email", "title": "A story you might relate to", "subject": "Someone who started right where you are", "body": "Hi [First Name] :)\n\nI wanted to share a quick story about [client names]. They were a long way out when we first talked, and they were not sure when the timing would be right.\n\nWe kept in touch, they watched the market with me, and when the right home came up they were ready. [One line on how it turned out.]\n\n[Insert video: Client Story]\n\nWhat is the one thing that would tell you it is time?", "video": "client-story"},
            {"day": 270, "channel": "email", "title": "Revisit the plan", "subject": "Want to revisit your plans together?", "body": "Hi [First Name] :)\n\nWe first connected a while back, and I know life can change a lot in a year. Have your plans shifted at all? Are you still thinking about a move down the road?\n\nI would love to sit down, revisit your timeline together and put a simple game plan in place, so you are ready the moment it feels right.\n\nDoes a weekday or a weekend work better for a quick coffee?"},
            {"day": 315, "channel": "text", "title": "Just popped in my head", "body": "Hi [First Name]! You just popped in my head.\n\nHow are things going with you guys?"},
            {"day": 360, "channel": "call", "title": "The annual call", "body": "Hi [First Name], it is [Your Name] :) It has been about a year since we first connected, and I wanted to call instead of email.\n\nWhere are you at with your plans?", "notes": "No answer? Voice note, same words. Then route them: a timeline moves the tag, none restarts the year."},
            {"day": 367, "channel": "tag", "title": "Route", "body": "Timeline: Lukewarm, Warm or Hot. None: restart at day 1.", "route_to": "restart", "notes": "Automatic default: anyone still Long-Term starts the year again. Refresh the market numbers and the story before it goes back out."},
        ],
    },
    {
        "slug": "bad-number-drip",
        "name": "Bad Number Drip",
        "kind": "nurture",
        "role": "primary",
        "trigger_segment": "bad_number",
        "exit_day": 101,
        "exit_rule": "Day 101: still tagged Bad Number means Long-Term Nurture. A working number or a timeline moves them earlier, any day.",
        "description": "The email-only campaign for a lead whose phone number does not work. Fourteen short emails over 100 days, each one ending in a single question they can answer from their phone.",
        "source_url": "https://drive.google.com/file/d/1nP7HlcI8MEh4HJApnOEjnhOTPikekVOO/view",
        "notes": _LAYER_NOTE + "\n\nSend from your real address, plain text, no header image. It should look like you typed it. An unsubscribe or a \"not looking, ever\" takes them off every campaign that day and marks them do not contact.",
        "steps": [
            {"day": 2, "channel": "email", "title": "Connect, and check the number", "subject": "Quick question, did I get the right number?", "body": "Hi [First Name] :)\n\nI noticed you have been looking at homes on my site, so I gave you a quick call. It looks like I missed you, or maybe I have the wrong number.\n\nEither way I wanted to say hi properly.\n\nWhat had you looking right now?\n\n[Your Name]"},
            {"day": 10, "channel": "email", "title": "Make it easier", "subject": "Are you searching on your phone or a computer?", "body": "Hi [First Name] :)\n\nQuick one. When you are browsing homes, are you usually on your phone or at a computer?\n\nI ask because there is an app connected to my site that makes saving favourites and catching new listings way easier on a phone. [Where to find it]\n\nWhich one are you on most?\n\n[Your Name]"},
            {"day": 15, "channel": "email", "title": "Their situation", "subject": "What is standing out so far?", "body": "Hi [First Name] :)\n\nYou have been looking for a couple of weeks now, so I am curious.\n\nWhat is standing out? An area, a style of home, a price point that keeps catching your eye?\n\nSend me the one you liked most and I will pull the sold prices around it so you know what it is actually worth.\n\n[Your Name]"},
            {"day": 20, "channel": "email", "title": "Their current home", "subject": "What is your current place like?", "body": "Hi [First Name] :)\n\nThought I would ask about the other half of this. What is your current place like, and what is it missing?\n\nMost people I work with are not just looking for a house. They are trying to fix something about the one they are in. Too small, too far, the yard, the stairs, the rent.\n\nWhat is the thing you would change first?\n\n[Your Name]"},
            {"day": 27, "channel": "email", "title": "The problem with the search", "subject": "Seeing the same listings over and over?", "body": "Hi [First Name] :)\n\nI feel like everyone hits this point. You have seen every listing in your range twice, and half of them you already ruled out.\n\nI set my clients up with a filtered search through my board's MLS portal. It only shows you what you have not seen, tracks what things actually sell for, and sometimes catches homes before they hit the big sites.\n\nWhat is your price range and your minimum beds and baths? I will set it up today.\n\n[Your Name]"},
            {"day": 35, "channel": "email", "title": "See it in person", "subject": "Want to see a few in person?", "body": "Hi [First Name] :)\n\nPhotos lie a little. Rooms look bigger, yards look flatter, and the highway is never in the shot.\n\nI do a low pressure exploratory tour with people at this stage. Four or five homes across your range, not to buy, just so you know what your money actually gets you. It usually makes everything click.\n\nDoes a weekday evening or a weekend work better for you?\n\n[Your Name]"},
            {"day": 42, "channel": "email", "title": "Has anything shifted", "subject": "Has your wishlist changed?", "body": "Hi [First Name] :)\n\nOnce people start really looking, the list almost always changes. The must-have garage becomes a nice-to-have. The area you never considered becomes the one you like.\n\nWhat has shifted for you since you started? Location, price, size, timing?\n\nTell me and I will update what you are seeing so it feels more like you.\n\n[Your Name]"},
            {"day": 52, "channel": "email", "title": "How to reach you", "subject": "What is the best way to reach you?", "body": "Hi [First Name] :)\n\nI want to make sure I am reaching you the way you actually like to be reached.\n\n• Email\n• Text\n• A quick call\n\nWhich one, and what is the best number or email for it?\n\n[Your Name]"},
            {"day": 65, "channel": "email", "title": "The money piece", "subject": "Have you talked to a mortgage specialist yet?", "body": "Hi [First Name] :)\n\nThought I would check in on the money side, because it changes everything about the search. Knowing your real number is what turns browsing into shopping.\n\nIf you have not talked to anyone yet, I can introduce you to [Mortgage Broker Name]. Super easy conversation, no obligation, and you walk away knowing exactly what you are working with.\n\nWhere are you at with financing right now: just starting, running numbers, or already approved?\n\n[Your Name]"},
            {"day": 75, "channel": "email", "title": "What waiting costs", "subject": "Curious, what is your read on the market?", "body": "Hi [First Name] :)\n\nYou have been watching for a couple of months now, so you have seen more than most people. What stands out to you? Prices, how fast things go, certain areas?\n\nAnd the real question I ask everyone at this point: if nothing changed for the next year, and you were still in your current place, how would that feel?\n\nWhat would that mean for you guys?\n\n[Your Name]"},
            {"day": 85, "channel": "email", "title": "What would need to happen", "subject": "What would make this the right time?", "body": "Hi [First Name] :)\n\nThought I would circle back :) I feel like most people know roughly what they want by now. The question is what has to happen for it to feel like the right time.\n\nIs it the numbers, finding the right home, or something on the selling side?\n\nTell me which one and I will send you the two or three homes that fit, or we can talk it through on a quick call this week. Which would help more?\n\n[Your Name]"},
            {"day": 90, "channel": "email", "title": "Open the door", "subject": "Can I clear one thing up for you?", "body": "Hi [First Name] :)\n\nEvery buyer I work with has one part of the process they are not sure about. The offer, the inspection, the deposit, the timing of selling and buying.\n\nWhat is the one piece I could clear up for you this week?\n\nSend it over and I will give you a straight answer.\n\n[Your Name]"},
            {"day": 95, "channel": "email", "title": "Coffee", "subject": "Coffee this week?", "body": "Hi [First Name] :)\n\nI would love to sit down for a coffee, on me. We can narrow down your criteria, talk through the market, and put a real plan together for when you are ready to move on something.\n\nHalf an hour, and you will leave knowing exactly what the next step is.\n\nDoes a weekday morning or an afternoon work better for you?\n\n[Your Name]"},
            {"day": 100, "channel": "email", "title": "Fix the number", "subject": "Is this still the best number for you?", "body": "Hi [First Name] :)\n\nQuick one so I get it right. Is this still the best number to reach you: [Phone Number]?\n\nIf it has changed, send me the new one and I will give you a quick call this week.\n\nWhat is the best time of day to catch you?\n\n[Your Name]"},
            {"day": 101, "channel": "tag", "title": "Move the tag", "body": "Still tagged Bad Number: Long-Term Nurture. A number or a timeline moves it earlier, any day.", "route_to": "long_term", "notes": "Automatic default: anyone still Bad Number on day 101 moves to Long-Term."},
        ],
    },
    {
        "slug": "buyer-course",
        "name": "Buyer Course",
        "kind": "course",
        "role": "layer",
        "layer_flag": "buying",
        "run_once": True,
        "exit_day": 25,
        "exit_rule": "Day 25 tags them Buyer Course Done. The course runs once per person.",
        "description": "The VIP Buyer Experience: nine short lessons from search to keys. The education layer that runs underneath every buyer campaign, on days that never land on a nurture email.",
        "source_url": "https://drive.google.com/file/d/1A499qbfdeyL1JROWvIIonUH9NidYvz9J/view",
        "notes": "Starts the day a buyer gets a Hot, Warm, Lukewarm or Long-Term segment (day 15 from The First 14 Days). Skip anyone whose card already says Buyer Course Done. Replies do not stop it; only a signed contract ends it early. Check the costs in lesson 4 against your area and your lawyer before you load it.",
        "steps": [
            {"day": 3, "channel": "email", "title": "Lesson 1: Welcome to the home buying process", "subject": "Your home buying course starts now", "body": "Hi [First Name] :)\n\nWhether this is your first home or you have bought before, the buying process has changed a lot. So over the next three weeks I am sending you a short video every few days that walks you through it step by step, from your search all the way to the keys.\n\nHere is how it works with me: new listings that match what you want come straight to your inbox, [your showing partner] books your showings, and when you find the one, I step in to build the strategy and negotiate your price and dates.\n\n[Insert video: Course Welcome]\n\nWhat are your absolute must-haves, so I can fine-tune your search?", "video": "course-welcome", "notes": "Text the same day: \"Hi [First Name]! I just sent you the first video in your home buying course. Did it land in your inbox?\""},
            {"day": 5, "channel": "email", "title": "Lesson 2: The consultation and your search setup", "subject": "Step one: the strategy call and your VIP buyer setup", "body": "Hi [First Name] :)\n\nThe very first step is a quick strategy session, on Zoom or over coffee. We go through the whole process, your VIP Buyer Package and your financing, so you know the timelines before we ever step into a house.\n\nThen I set you up with your own MLS search with the sold listings included. Watching what homes list for and what they actually sell for is how you get a feel for value fast. List price is what a seller hopes for. Sold is what the market paid.\n\n[Insert video: Search Setup]\n\nDoes a weekday or a weekend work better for your strategy session?", "video": "search-setup"},
            {"day": 7, "channel": "email", "title": "Lesson 3: Exploratory tours, why they matter", "subject": "The power of exploratory tours", "body": "Hi [First Name] :)\n\nBefore you even think about making an offer, we go on what I call an exploratory tour. A few homes in different areas and price points, so you can feel what your budget gets you, which layouts work, and what looks great online but feels different in person.\n\nI hear \"we are not looking to buy just yet\" all the time, and that is exactly why this works. It is not about buying. It is about clarity, and it is the thing my clients say helped the most.\n\n[Insert video: Exploratory Tour]\n\nDoes an evening or a weekend work better for your tour?", "video": "exploratory-tour"},
            {"day": 11, "channel": "email", "title": "Lesson 4: Understanding your numbers", "subject": "Financing 101: what you need to know", "body": "Hi [First Name] :)\n\nFinancing can feel like a lot, so let us break it down.\n\n• Get pre-approved early. It is heartbreaking to fall in love with a home and then find out your budget is not what you thought\n• Your down payment is not the only cost. Plan for a home inspection ($400 to $600), an appraisal if your lender asks ($250 to $350), legal fees ($1,500 to $3,000), property transfer tax if it applies, and moving and setup\n• The right mortgage broker matters. When your broker, your lawyer and I are on the same timeline, everything moves smoother\n\n[Insert video: Your Numbers]\n\nDo you already have a mortgage broker, or should I connect you with one of mine?", "video": "your-numbers"},
            {"day": 13, "channel": "email", "title": "Lesson 5: Booking showings and asking the right questions", "subject": "Booking showings and what to look for", "body": "Hi [First Name] :)\n\nOnce we have narrowed down a few homes you like, we start booking showings. Here is what to look at beyond the obvious:\n\n• What you cannot change: the location, the lot, the layout and the light\n• The big-ticket items: the roof, windows, furnace and hot water tank, and how old they are\n• How it lives: noise, parking, and where the sun sits in the afternoon\n\nAfter each one, ask yourself if it beats the last one. That is how you recognise the right home the minute you walk in.\n\n[Insert video: Showings]\n\nWhich of your must-haves do you think will hold up once you see homes in person?", "video": "showings"},
            {"day": 16, "channel": "email", "title": "Lesson 6: Writing offers and negotiating", "subject": "How offers and negotiations work", "body": "Hi [First Name] :)\n\nWhen you find the one, we book a second showing and take a deep dive together. This is where I step in with a strategic lens.\n\nA strong offer is not just a price. We look at what similar homes actually sold for, how long this one has been sitting and what the seller needs, then we build your price, your subjects and your dates around what matters most to you.\n\nYou will never be pressured into a number. You get the facts, and you make the call.\n\n[Insert video: Offer Strategy]\n\nIf you found the one tomorrow, what would need to be true for you to feel confident writing an offer?", "video": "offer-strategy"},
            {"day": 18, "channel": "email", "title": "Lesson 7: What happens after an accepted offer", "subject": "We got the home! Now what?", "body": "Hi [First Name] :)\n\nOnce your offer is accepted, the real due diligence begins, and I send you a checklist so nothing gets missed:\n\n• Your deposit goes in to secure the home\n• We book the home inspection. Try to be there for the last 30 minutes so you can ask the inspector questions yourself\n• Your broker finalizes your mortgage and may order an appraisal, and you set up your home insurance\n• Once everything checks out, we remove subjects and send it all to your lawyer\n\n[Insert video: After the Accepted Offer]\n\nDo you have a home inspector in mind, or would you like my list?", "video": "after-the-accepted-offer"},
            {"day": 22, "channel": "email", "title": "Lesson 8: Final steps before possession", "subject": "Preparing for possession day", "body": "Hi [First Name] :)\n\nThe countdown is on. Once subjects are removed, here is what happens before you get the keys:\n\n• You book your lawyer or notary appointment to sign the transfer and bring in the rest of your down payment\n• Book your movers or truck early, and set up your utilities. Internet usually books a week out, and nobody wants to live without wifi\n• One big no-no: no new credit cards, loans or big purchases like a car or new furniture until you have the keys\n\n[Insert video: Possession Day]\n\nWhat part of moving day do you most want handled for you?", "video": "possession-day"},
            {"day": 24, "channel": "email", "title": "Lesson 9: Bonus: assessments vs appraisals vs list prices", "subject": "Bonus: assessments vs appraisals vs list prices", "body": "Hi [First Name] :)\n\nThese three numbers cause more confusion than anything else in real estate, so here they are in plain English:\n\n• Assessed value: what BC Assessment says the home was worth on July 1 of last year. It sets your property taxes, and it is often out of date\n• Appraised value: what your lender's appraiser says it is worth today. It decides how much the bank will lend\n• List price: what the seller is asking. A starting point, not a value\n\nThe number that matters most is what similar homes actually sold for. That is what we build your offer on.\n\n[Insert video: Assessments vs Appraisals]\n\nWhich home have you seen where the list price surprised you?", "video": "assessments-vs-appraisals"},
            {"day": 25, "channel": "tag", "title": "Buyer Course Done", "body": "The course runs once per person.", "route_to": "done"},
        ],
    },
    {
        "slug": "seller-course",
        "name": "Seller Course",
        "kind": "course",
        "role": "layer",
        "layer_flag": "selling",
        "run_once": True,
        "exit_day": 27,
        "exit_rule": "Day 27 tags them Seller Course Done.",
        "description": "What selling your home with us actually looks like, in seven short lessons. The optional layer you add when a lead tells you they are selling, or selling to buy.",
        "source_url": "https://drive.google.com/file/d/1SIaJc8rGn_AIj-vFOjhi7usAOEZ68yIx/view",
        "notes": "Add it the day you learn they are selling. Built on different days from the Buyer Course, so a move-up client gets both without two emails landing together. Found out partway through? Start it that day, and if a lesson ever lands on the same day as a nurture email, move the lesson one day later. Only a signed listing agreement ends it early.",
        "steps": [
            {"day": 6, "channel": "email", "title": "Lesson 1: Welcome to the seller process", "subject": "Selling your home? Here is what you can expect from us", "body": "Hi [First Name] :)\n\nSelling a home is a big deal, emotionally and financially. That is why we put this series together, to walk you through every step of the journey with us.\n\nWhether you have sold before or this is your first time, you will see how we work with sellers, what makes our process different, and how we position your home to sell for top dollar. Each email comes with a short video you can come back to anytime.\n\n[Insert video: Seller Welcome]\n\nWhat has you thinking about selling right now?", "video": "seller-welcome"},
            {"day": 8, "channel": "email", "title": "Lesson 2: The pre-listing package", "subject": "What happens before the sign even goes up?", "body": "Hi [First Name] :)\n\nBefore we put a sign in the yard or list your home on the MLS, we start with strategy. You get our digital Seller Package with:\n\n• Examples of our listing videos and marketing\n• Our pre-listing strategy to create urgency and demand\n• A menu of optional add-ons, so you pick what fits your goals\n\n[Insert video: Pre-Listing Game Plan]\n\nShould I send your Seller Package by email or by text?", "video": "pre-listing-game-plan"},
            {"day": 12, "channel": "email", "title": "Lesson 3: The walkthrough and the deep dive", "subject": "What is your home really worth?", "body": "Hi [First Name] :)\n\nOnce you have looked through the pre-listing package, we book a walkthrough. This is where I learn everything about your home: the updates, the quirks, and the features you love.\n\nThen I do a deep market dive and build your pricing sandwich: where your home sits against similar homes that have sold and the ones listed right now. We meet again and walk through the numbers and your pricing options together.\n\n[Insert video: Home Evaluation]\n\nWhich updates have you done that you would want buyers to notice first?", "video": "home-evaluation"},
            {"day": 17, "channel": "email", "title": "Lesson 4: Pre-marketing and the listing launch", "subject": "How we create demand for your home", "body": "Hi [First Name] :)\n\nBefore the listing goes live, we schedule photos and measurements and build marketing momentum. We do not throw it on the market and hope for the best.\n\nWe build urgency, coordinate ads and get buyer eyes on your home ahead of time. I call it creating a bottleneck of buyers, so your launch day brings traffic and excitement.\n\n[Insert video: Pre-Launch Strategy]\n\nWhat time of year were you hoping to have it on the market?", "video": "pre-launch-strategy"},
            {"day": 19, "channel": "email", "title": "Lesson 5: Showings and the feedback loop", "subject": "What to expect during showings", "body": "Hi [First Name] :)\n\nOnce your listing is live, we handle every appointment request, coordinate the showings and gather feedback from every buyer's agent.\n\nIf we are not getting traction, you hear it from us first, with the data to guide the next step. You stay in the loop without being overwhelmed.\n\n[Insert video: Showings and Feedback]\n\nWhat would you want to hear from me after every showing?", "video": "showings-and-feedback"},
            {"day": 23, "channel": "email", "title": "Lesson 6: Offers and negotiations", "subject": "What happens when offers come in?", "body": "Hi [First Name] :)\n\nWhen an offer comes in, our work is not done. We contact every agent who has shown your home to see if their buyers are interested too, which can lead to multiple offers and more leverage for you.\n\nAnd when we negotiate, the goal is to make the deal as sticky as possible, so it does not fall apart later. Price matters, and so do the dates and the subjects.\n\n[Insert video: Negotiation Strategy]\n\nIf two offers came in, what would matter more to you, the price or the dates?", "video": "negotiation-strategy"},
            {"day": 26, "channel": "email", "title": "Lesson 7: After the sale", "subject": "What happens after subjects are removed?", "body": "Hi [First Name] :)\n\nEven after your home is sold, we are still right here. You get a full checklist to prep for moving day, transfer your utilities, forward your mail and more, so it all feels smooth.\n\n[Insert video: After the Sale]\n\nWhere are you hoping to land after this move?", "video": "after-the-sale", "notes": "That question matters. If they are buying next, their answer is your next deal."},
            {"day": 27, "channel": "tag", "title": "Seller Course Done", "body": "The course runs once per person.", "route_to": "done"},
        ],
    },
    {
        "slug": "raving-fan-club",
        "name": "Raving Fan Club",
        "kind": "playbook",
        "role": "primary",
        "trigger_segment": "soi",
        "exit_day": 365,
        "exit_rule": "The rhythm repeats every year. Past clients and referral sources never fall off the list.",
        "description": "A referral program your clients actually talk about. Personal asks timed right after a win, a real check-in every 60 to 90 days with no ask attached, tiered holiday recognition, a yearly draw, a private past-client group with a monthly giveaway, and at least one appreciation event a year.",
        "source_url": "https://drive.google.com/file/d/1kVrZYpBQfFssiuqoNiCgg5zVoLD4Ija1/view",
        "notes": "THE SYSTEM: Ask → Thank → Tag → Recognize → Invite → Repeat.\n\nAsk right after a win (possession day, or two weeks in), personally, worded as a favour, and as an introduction: \"Would you be comfortable introducing us by text?\" Thank every referral within the week with a handwritten card and a coffee gift card, before you know if it closes. Tag every referral source in your CRM. Recognize with tiered holiday gifts (A: multiple transactions and referrals, B: multiple referrals, C: everyone else), an annual draw where every referral is an entry, and newsletter shout-outs. Invite them to the private past-client group with a giveaway every month. Book next quarter's event before this one is over.\n\nCheck with your broker first. What you can give for a referral changes by province and state.",
        "steps": [
            {"day": 1, "channel": "text", "title": "The referral ask", "body": "Can I ask you a huge favour? Who do you know that's thinking about buying or selling this year? I'd so appreciate you sending them my way.", "notes": "Personal, one person at a time, right after a win. Pair it with the Google review ask. Then offer the introduction: \"Would you be comfortable introducing us by text? If it's easier, you can just forward this: Hey [Name], this is [Your Name], the realtor who helped us with our place. I mentioned you were thinking about moving this year, so I wanted to connect you two. I'll let you take it from here!\""},
            {"day": 75, "channel": "call", "title": "Check-in, no ask", "body": "Hi [First Name], it is [Your Name] :) You popped into my head and I wanted to see how things are going at the house.\n\nWhat has been the best part of being there?", "notes": "A real check-in every 60 to 90 days, with no ask attached. Voice note if no answer."},
            {"day": 150, "channel": "email", "title": "Monthly giveaway note", "subject": "A little thank-you this month", "body": "Hi [First Name] :)\n\nQuick fun one this month. I'm doing a [giveaway item] for my past-client group. If you want in, just reply to this email or comment on the post in the group. No catch, just a little thank-you for being part of my world.\n\nWhat would you want to win next month?", "notes": "Announce the winner in the group and in your newsletter. Every entry is a conversation that comes to you."},
            {"day": 225, "channel": "call", "title": "Check-in, no ask", "body": "Hi [First Name], it is [Your Name] :) Thinking about you guys. How is everyone doing?\n\nAnything around the house I can help with, a trade, a number, a neighbour thinking about selling?", "notes": "Home equity check-in works well here: pull recent sales near their home and offer a 15 minute call. Give before you ask."},
            {"day": 300, "channel": "text", "title": "Home anniversary", "body": "Hi [First Name]! Happy home anniversary :) Hard to believe it has been a year. I just pulled what homes around you have been selling for, want me to send it over?", "notes": "One of the four high points to ask again: offer accepted, possession day, 30 days in, the first home anniversary."},
            {"day": 340, "channel": "task", "title": "Holiday recognition", "body": "Tier them: A (multiple transactions and referrals) gets a one-night stay plus a dining gift card, B (multiple referrals) gets a curated local gift basket, C (everyone else) gets a personalized holiday card. Announce the annual draw winner in your yearly postcard.", "notes": "Broker-approved gifts only."},
            {"day": 365, "channel": "tag", "title": "Repeat the rhythm", "body": "The club runs all year. Start the rhythm again.", "route_to": "restart"},
        ],
    },
    {
        "slug": "top-25",
        "name": "Top 25",
        "kind": "playbook",
        "role": "layer",
        "description": "The 25 people most likely to buy or sell first. Hot fills it first, then Warm, then Lukewarm. Reviewed every Monday in 20 minutes, and it opens your power hour before anyone else gets a call.",
        "source_url": "https://drive.google.com/file/d/10MserPpCrqxav7HOS6h2GjU3otuOgpJi/view",
        "notes": "WHO MAKES THE LIST: every Hot lead first, then Warm (pre-approval or firm date first), then Lukewarm (whose pre-approval is coming, who said spring, whose mortgage renews) until you have 25 names. Twenty-five is the number, not forty: when a new Hot lead comes in and the list is full, the coolest name comes off.\n\nTHE MONDAY REVIEW: anyone new go Hot this week? On, at the top. Anyone close, go quiet for two months, or say never? Off. Warm turned Hot? Move them up. Who is owed a touch? Mark them.\n\nEVERY CARD HAS: full name and preferred name, mobile and email, home address, birthday and home anniversary, family, pets and personal notes, lead segment and next follow-up date.\n\nKeep it light: Top 25 people get calls, texts, voice notes and video only. Pop-bys, cards and coffee dates belong to your sphere and Raving Fan rhythms.",
        "steps": [
            {"day": 1, "channel": "task", "title": "Monday review", "body": "20 minutes before your power hour: fill the list Hot first, then Warm, then Lukewarm. Anyone new go Hot? On. Anyone closed or quiet for two months? Off. Check every card has the must-haves.", "notes": "Add this contact to your Top 25 with their segment, price point, timeline and next touch."},
        ],
    },
]


def campaign_by_slug(slug: str) -> dict[str, Any] | None:
    for campaign in CAMPAIGNS:
        if campaign["slug"] == slug:
            return campaign
    return None


def video_by_slug(slug: str) -> dict[str, Any] | None:
    for video in VIDEOS:
        if video["slug"] == slug:
            return video
    return None


__all__ = [
    "CAMPAIGNS",
    "SEGMENTS",
    "TEMPLATE_VERSION",
    "VIDEOS",
    "campaign_by_slug",
    "video_by_slug",
]
