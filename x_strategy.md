# Twitter/X Algorithm Playbook: The Complete Guide to Algorithm-Optimized Content

**Universal principles for maximizing reach and engagement on X's recommendation system.**

---

## Table of Contents

1. [How the Algorithm Works](#how-the-algorithm-works)
2. [The 7 Algorithm Levers](#the-7-algorithm-levers)
3. [Content Strategy Framework](#content-strategy-framework)
4. [Posting Strategy](#posting-strategy)
5. [Content Formats by Algorithm Score](#content-formats-by-algorithm-score)
6. [Metrics That Matter](#metrics-that-matter)
7. [Execution Checklist](#execution-checklist)
8. [Common Pitfalls](#common-pitfalls)

---

## How the Algorithm Works

### The Two-Stage Pipeline

X's recommendation system operates in two stages:

**Stage 1: Retrieval** (millions of tweets → ~1,000 candidates)
- Uses a **two-tower ML model** with user embeddings and content embeddings
- Finds tweets matching your engagement history and interests
- Combines:
  - **In-network content**: From accounts you follow
  - **Out-of-network content**: ML-discovered from the global tweet corpus

**Stage 2: Ranking** (~1,000 candidates → your feed)
- Uses a **Grok transformer** to predict engagement probabilities
- Scores content using a **multi-action weighted formula**:
  ```
  Score = w1×P(like) + w2×P(retweet) + w3×P(quote) + w4×P(reply)
        + w5×P(click) + w6×P(share) + w7×P(follow_author)
        + w8×P(photo_expand) + w9×P(video_quality_view)
        - w10×P(not_interested) - w11×P(block) - w12×P(mute)
  ```

**Key insight**: The algorithm rewards content triggering **multiple engagement types simultaneously**. A tweet with likes + retweets + replies scores exponentially higher than a tweet with just likes.

---

## The 7 Algorithm Levers

### 1. Multi-Action Content Design (HIGHEST IMPACT)

**Why it matters**: Each engagement type has a separate weight in the scoring formula. Content that triggers 3+ actions gets amplified.

**Design principle**: Every tweet should aim for 3+ engagement types.

**Engagement type weights** (approximate, from highest to lowest):
1. **Follow author** - Strongest signal (new follower)
2. **Reply** - High weight (conversation starter)
3. **Retweet** - Medium-high weight (amplification)
4. **Quote** - Medium-high weight (amplification + commentary)
5. **Video quality view** - High weight (video watched beyond minimum duration)
6. **Photo expand** - Medium weight (visual interest)
7. **Click** - Medium weight (link engagement)
8. **Like** - Base weight (basic agreement)

**Multi-action content formula**:
```
[Hook with number/result] → curiosity, click
+ [Proof/data] → likes (agreement)
+ [Insight/lesson] → retweets (value to share)
+ [Question/takeaway] → replies (discussion)
+ [Image/video] → photo_expand or VQV
+ [Follow CTA] → follows
```

**Example**:
```
❌ Single-action tweet:
"Great article about marketing! [link]"
→ Only gets clicks → LOW SCORE

✅ Multi-action tweet:
"We increased conversion by 340% using this one psychological trigger.

Here's the breakdown:
- Before: 2.1% conversion
- After: 9.2% conversion
- Change: Added scarcity countdown timer

Would you use this tactic or is it too aggressive?

[Chart showing conversion curve]

Follow for more marketing experiments"
→ Gets likes, retweets, replies, clicks, photo_expand, follows → VERY HIGH SCORE
```

### 2. Video Quality Views (VQV) - The Secret Signal

**What is VQV**: `video_quality_view` = videos watched beyond minimum duration / videos served

**Why it matters**: VQV is a separate, high-weight signal in the algorithm. Most creators don't optimize for it.

**VQV optimization tactics**:

| Tactic | Why it works |
|--------|--------------|
| **Keep videos under 60 seconds** | Higher completion rate = more VQVs |
| **Hook in first 2 seconds** | Viewers decide quickly if they'll keep watching |
| **Show, don't tell** | Screen recordings > talking heads |
| **Add text overlays** | Accessibility + clarity |
| **End with clear CTA** | "Save this" = share signal, "Follow for more" = follow signal |

**Video format best practices**:
```
✅ Good: [30-second screen recording]
Caption: "watch our agent debug itself in real-time"
Shows: error → agent notices → agent fixes → confirms
CTA: "follow for more breakdowns"

❌ Bad: [2-minute talking head]
Caption: "Let me show you our system..."
Problem: Low completion rate, no hook, weak CTA
```

**Target VQV rate**: 40%+ (excellent: 60%+)

### 3. Photo Expansion Optimization

**What is photo_expand**: Users tapping to view your image in full screen

**Why it matters**: Photo expansion is a separate positive signal in the scoring formula.

**Photo expansion tactics**:

| Content Type | Why it expands |
|--------------|----------------|
| **Text-on-images** with key stats | Users tap to read the details |
| **Screenshots with annotations** | Devs/technical users expand to see code/logic |
| **Before/after comparisons** | Visual curiosity drives expansion |
| **Thread summaries as infographics** | Value extraction |
| **Charts/graphs** | Users want to see the data clearly |

**Example**:
```
Tweet: "our token costs dropped 73%"

Image: [Screenshot of billing page]
       Text overlay: "Before: $0.50/query → After: $0.02/query"

Result: Users tap to read the details → photo_expand signal → higher score
```

**Target photo expansion rate**: 15%+ (excellent: 25%+)

### 4. Author Diversity Management

**What is author diversity**: X applies a penalty when the same author appears too frequently in your feed.

**The implication**: Posting frequency has **diminishing returns**.

**Optimal posting schedule**:
```
Post 1: 7:00am - 8:00am
         ↓ [4-5 hour gap]
Post 2: 12:00pm - 1:00pm
         ↓ [5-6 hour gap]
Post 3: 6:00pm - 7:00pm
```

**Anti-pattern to avoid**:
```
❌ Bad: 10 posts in one hour (8:00am, 8:10am, 8:20am, etc.)
→ Author diversity penalty kicks in at post 3
→ Each post gets progressively lower reach
→ Post 10 reaches < 10% of post 1's audience

✅ Good: 3 posts spaced 4-5 hours apart
→ Each post gets full algorithm consideration
→ Author diversity penalty never triggers
→ Consistent reach across all posts
```

**Real-world impact**:
```
Account A: 10 posts/day, 1 hour apart → 1.2K impressions/post
Account B: 3 posts/day, 5 hours apart → 8.7K impressions/post

Result: 70% less content = 115% more reach
```

### 5. Recency & Freshness Leverage

**The velocity window**: Posts that get engagement quickly (first 5-30 minutes) get amplified. Posts that sit dormant get buried.

**The golden window**:
```
0-5 min:    Algorithm tests content (shows to ~100 followers)
5-30 min:   If engagement > threshold, amplification begins
30-60 min:  Peak visibility
60+ min:    Decay begins
```

**Critical tactic**: Post when you can engage for the first 30 minutes.

**Bad**:
```
Post at 8:00am → go to meeting → check Twitter at 10:00am
→ Missed velocity window
→ Content sits dormant
→ Algorithm buries it
```

**Good**:
```
Post at 8:00am → stay on Twitter for 30 minutes → reply to every comment
→ High velocity
→ Algorithm amplifies
→ 10x reach
```

### 6. Negative Signal Avoidance

**Negative signals** (high negative weights):
- `block` - User blocks author
- `mute` - User mutes author
- `report` - User reports content
- `not_interested` - User swipes past without engaging

**What triggers negative signals**:

| Signal | Triggers | Prevention |
|--------|----------|------------|
| **Mute** | Thread spam (7-part threads with 1 line each), repetitive content, same format every day | Vary content formats, quality over quantity |
| **Block** | Controversial takes, harassment, aggressive self-promotion | Stay in your lane, be helpful not spammy |
| **Report** | Policy violations, spam, misleading content | Follow X's terms of service |
| **Not interested** | Weak hooks, uninteresting content, irrelevant topics | Strong hooks, relevant to your niche |

**The mirror test**: Would YOU stop scrolling to read this? If no, don't post.

### 7. Out-of-Network Discovery

**What is Phoenix**: X's out-of-network recommendation system using a two-tower model.

**How Phoenix works**:
1. Builds an embedding of you based on your engagement history
2. Builds embeddings of all tweets
3. Finds tweets with similar embeddings to your interests
4. Predicts if you'll engage
5. Shows the highest-scoring out-of-network content

**Optimization tactics**:

| Tactic | How it helps |
|--------|--------------|
| **Topic consistency** | Algorithm learns what you're about (90% of content = your niche) |
| **Use relevant keywords** | Signals to the algorithm what your content is about |
| **Engage with target accounts** | When you engage with others in your niche, algorithm shows your content to similar users |

**Example**:
```
You engage with @marketingexpert
→ Algorithm clusters you with "marketing" interest group
→ Your content gets shown to others in that cluster
→ They engage → Algorithm confirms your topic authority
→ More out-of-network reach
```

**Target out-of-network impression rate**: 40%+ (means you're growing beyond followers)

---

## Content Strategy Framework

### The 3 Content Buckets

**1. Authority Building (40% of posts)**
- Original insights, frameworks, data
- Establishes your expertise
- Drives follows and long-term audience growth

**2. Engagement Bait (30% of posts)**
- Questions, hot takes, polls
- Sparks conversations
- Drives replies (high-weight signal)

**3. Value Sharing (30% of posts)**
- Tips, tutorials, quick wins
- Provides immediate value
- Drives retweets and saves

### The A/B Testing Framework

**Test variables**:
1. **Hook style** (Number, curiosity, controversy, story)
2. **Content format** (Thread, single tweet, video, image)
3. **CTA type** (Follow, save, share, reply)
4. **Posting time** (Morning, lunch, evening)
5. **Hashtag usage** (None vs. 1-2 relevant)

**Testing process**:
```
Week 1: Post 3x/day using Strategy A
Week 2: Post 3x/day using Strategy B
Compare: MAER (multi-action engagement rate), VQV, photo expansion, follows
Winner: Scale up strategy with higher metrics
```

### Topic Consistency Rule

**The 90% rule**: 90% of your content should be about your core topic.

**Why**: The Phoenix (out-of-network) system learns what you're about. If you post consistently about one topic, it learns to show your content to people interested in that topic.

**Example**:
```
❌ Scattershot approach:
- Monday: Marketing tips
- Tuesday: Your political opinion
- Wednesday: Marketing tips
- Thursday: Your vacation photos
- Friday: Marketing tips

→ Algorithm can't figure out what you're about
→ No out-of-network reach
→ Stuck with your followers only

✅ Focused approach:
- Monday: Marketing tips
- Tuesday: Marketing case study
- Wednesday: Marketing framework
- Thursday: Marketing failure story
- Friday: Marketing question/poll

→ Algorithm learns: "This person is about marketing"
→ Shows content to people interested in marketing
→ Out-of-network reach grows
```

---

## Posting Strategy

### Daily Rhythm

**Volume**: 2-3 original tweets or threads per day (NOT more)

**Engagement**: 5-10 replies/quote tweets per day

**Ratio**: 80% replies, 20% original content

**Why**: Your replies on others' content build your following faster than your own tweets.

### Optimal Posting Schedule

**For general audiences**:
- 7:00-9:00am local time (morning scroll)
- 11:00am-1:00pm (lunch break)
- 6:00-8:00pm (evening)

**For B2B/professional audiences**:
- 8:00-10:00am (before work)
- 12:00-2:00pm (lunch)
- 5:00-7:00pm (after work)

**For consumer/lifestyle audiences**:
- 9:00-11:00am (mid-morning)
- 7:00-9:00pm (primetime)

**Critical**: Post when you can engage for the first 30 minutes (velocity window).

### Weekly Rhythm

| Day | Content Focus | Format | Why |
|-----|---------------|--------|-----|
| Mon | Quick win | Tweet + image | Start week strong with photo_expand |
| Tue | Hot take | Thread | Sparks replies (high-weight signal) |
| Wed | Tutorial | Video or thread | Mid-week depth, VQV if video |
| Thu | Story/Case study | Thread | Authenticity drives engagement |
| Fri | Question/poll | Tweet | Discussion for weekend |
| Sat | Replies only | Engagement | Rest day, build relationships |
| Sun | Replies only | Engagement | Rest day, build relationships |

**Why this works**:
- Varies content format (avoids mute triggers)
- Gives 2-day break from posting (resets author diversity)
- Mon-Fri capture weekdays (peak traffic)
- Sat-Sun focus on engagement (builds relationships)

### The Reply Strategy (Primary Growth Mechanic)

**Why it works**: When you reply to someone with an audience, their audience sees your reply. If your reply is valuable, some of their audience follows you.

**Value-adding reply formula**:
```
[Agreement or insight]: "interesting point about X"

[Your experience]: "we found Y when we tried that"

[Question or expansion]: "have you seen Z affect this?"
```

**Bad reply**:
```
great insight! thanks for sharing.
```

**Good reply**:
```
interesting point about email subject lines.

we found that questions in subject lines increased open rates by 23%.
but only when they were genuine questions, not clickbait.

curious if you've seen similar?
```

**Reply targets**:
1. **Big accounts in your niche** (their audience = your potential followers)
2. **Peers with similar audience size** (they might reply back = more visibility)
3. **Up-and-coming accounts** (they remember who supported them early)

---

## Content Formats by Algorithm Score

| Format | Primary Signals | Secondary Signals | Algorithm Friendliness |
|--------|-----------------|-------------------|------------------------|
| **Short video (<60s)** | VQV, dwell | Likes, follows | ⭐⭐⭐⭐⭐ HIGHEST |
| **Hot take thread** | Replies, quotes | Likes, retweets | ⭐⭐⭐⭐⭐ VERY HIGH |
| **Quick win tweet** | Retweets | Likes, clicks | ⭐⭐⭐⭐ HIGH |
| **Screenshot + text** | Photo expand | Likes, retweets | ⭐⭐⭐⭐ HIGH |
| **Tutorial thread** | Retweets, saves | Likes, follows | ⭐⭐⭐⭐ HIGH |
| **Question tweet** | Replies | Likes, follows | ⭐⭐⭐ MEDIUM |
| **Opinion piece** | Likes, quotes | Replies | ⭐⭐⭐ MEDIUM |
| **Link bait** | Clicks | (low other signals) | ⭐ LOW (single-action) |

### Thread Optimization

**Optimal thread structure**:
```
Tweet 1: Hook + number/result + (optional) image
Tweet 2: Context/background
Tweet 3: First insight or step
Tweet 4: Second insight or step
Tweet 5: Third insight or step
Tweet 6: Summary + takeaway
Tweet 7: Follow CTA
```

**Anti-pattern**: 7-part thread where each tweet has 1 line.

**Why it fails**: Low value per tweet, triggers mute signals.

**Instead**: Pack value into every tweet. If it's not valuable standalone, don't post it.

### Single Tweet Optimization

**Optimal single tweet structure**:
```
[Hook with number/result]
|
+-- [Proof/data]
|
+-- [Insight/lesson]
|
+-- [Image/screenshot]
|
+-- [Follow CTA]
```

**Example**:
```
We increased email open rates by 47% with one subject line change.

Old: "Monthly newsletter"
New: "5 marketing mistakes you're making"

What changed: Curiosity + specificity + negative framing (people want to avoid mistakes)

[Chart showing open rates]

Follow for more marketing experiments
```

---

## Metrics That Matter

### Vanity Metrics (Ignore)

- Total follower count (does not drive reach)
- Total impressions (without context, meaningless)
- "Virality" (one-off spikes don't build audience)
- Likes only (single-action, low algorithm value)

### Algorithm Signals (What Actually Drives Reach)

#### Primary Metrics

**Multi-Action Engagement Rate (MAER)**:
```
MAER = (likes × 1 + retweets × 2 + replies × 3 + quotes × 2
        + follows × 5 + clicks × 1.5) / impressions

Target: 8%+
Excellent: 15%+
```

**Video Quality View (VQV) Rate**:
```
VQV = videos watched > minimum duration / videos served

Target: 40%+
Excellent: 60%+
```

**Photo Expansion Rate**:
```
Expansion = photo_expands / impressions

Target: 15%+
Excellent: 25%+
```

**Follow Conversion Rate**:
```
Follows = new_follows / impressions

Target: 0.5%+
Excellent: 1%+
```

#### Secondary Metrics

**Reply Depth Ratio**:
```
RDR = replies with 100+ chars / total replies

Target: 30%+
```

**Out-of-Network Impressions**:
```
OON = impressions from non-followers / total impressions

Target: 40%+
```

**Velocity Score** (engagement in first 30 minutes):
```
Velocity = (engagement in first 30min) / total engagement

Target: 40%+
```

#### Negative Signals to Monitor

| Metric | Threshold | Action |
|--------|-----------|--------|
| Mute rate | > 0.1% of impressions | Post less, vary content |
| Not interested rate | > 80% swipe past | Fix your hooks |
| Block/Report rate | > 0.01% | STOP. Reassess strategy |

### Weekly Review Questions

1. Which content had highest MAER?
2. Which videos had highest VQV?
3. What photo expansion rate am I getting?
4. What's my out-of-network impression ratio?
5. What's my velocity score?
6. Which content triggered follows?
7. Any negative signals?
8. What topics resonate?
9. What multi-action content performed best?

---

## Execution Checklist

### Before Posting

**Content design**:
- [ ] Does this trigger 3+ engagement types?
- [ ] Can I add a video or image for VQV or photo_expand?
- [ ] Is the hook compelling enough to stop the scroll?
- [ ] Does this align with my topic authority? (90% rule)

**Algorithm optimization**:
- [ ] Am I posting during my audience's peak hours?
- [ ] Have I posted in the last 3 hours? (author diversity)
- [ ] Would this trigger negative signals (block, mute, report)?
- [ ] Can I add a follow CTA to capture the engagement?

**Quality check**:
- [ ] Is this valuable or interesting to my target audience?
- [ ] Would I stop scrolling to read this? (mirror test)
- [ ] Is the writing clear and concise?

### After Posting (First 30 Minutes)

- [ ] Stay on Twitter and engage with every reply
- [ ] Reply to comments quickly (signals activity to algorithm)
- [ ] Post 2-3 quotes of valuable replies (multiplies signals)
- [ ] Don't post again for 3-4 hours (avoid author diversity penalty)

### Weekly

- [ ] Review metrics (MAER, VQV, photo expansion, OON)
- [ ] Identify top-performing content
- [ ] Identify underperforming content
- [ ] Test one variable (hook, format, time, CTA)
- [ ] Adjust strategy based on data

---

## Common Pitfalls

### Pitfall 1: Posting Too Frequently

**Mistake**: Posting 10+ times per day

**Result**: Author diversity penalty kicks in, each post gets progressively less reach

**Fix**: Post 2-3 times per day, spaced 4-5 hours apart

### Pitfall 2: Single-Action Content

**Mistake**: Posting content that only gets likes

**Result**: Low algorithm score, limited reach

**Fix**: Design every tweet to trigger 3+ engagement types

### Pitfall 3: Ignoring the Velocity Window

**Mistake**: Posting then going offline for hours

**Result**: Miss the critical first 30 minutes when algorithm decides whether to amplify

**Fix**: Post when you can engage for the first 30 minutes

### Pitfall 4: Inconsistent Topics

**Mistake**: Posting about everything (your niche + politics + personal life + random thoughts)

**Result**: Algorithm can't figure out what you're about, no out-of-network reach

**Fix**: 90% rule - 90% of content should be about your core topic

### Pitfall 5: Thread Spam

**Mistake**: 7-part threads where each tweet has one line

**Result**: Low value, triggers mute signals, author diversity penalty

**Fix**: Pack value into every tweet, or use single tweets instead

### Pitfall 6: Ignoring Negative Signals

**Mistake**: Continuing to post content that people mute or swipe past

**Result**: Accumulated negative signals permanently hurt reach

**Fix**: Monitor mute rate and not-interested rate, adjust strategy

### Pitfall 7: Chasing Vanity Metrics

**Mistake**: Focusing on follower count or total impressions

**Result**: Posting content that looks good but doesn't drive algorithmic signals

**Fix**: Focus on MAER, VQV, photo expansion, follow conversion

---

## Quick Reference

### The Algorithm Formula (Simplified)

```
Score = (likes × 1) + (retweets × 2) + (replies × 3) + (quotes × 2)
        + (follows × 5) + (clicks × 1.5) + (photo_expands × 1.5)
        + (video_quality_views × 2)
        - (blocks × 10) - (mutes × 5) - (not_interested × 3)
```

### Optimal Daily Schedule

```
8:00am  - Post 1 (engage for 30 min)
1:00pm  - Post 2 (engage for 30 min)
6:00pm  - Post 3 (engage for 30 min)
All day - 5-10 replies to others' content
```

### Optimal Weekly Schedule

```
Mon - Quick win + image
Tue - Hot take thread
Wed - Tutorial (video if possible)
Thu - Case study thread
Fri - Question/poll
Sat - Replies only
Sun - Replies only
```

### Target Metrics

| Metric | Target | Excellent |
|--------|--------|-----------|
| MAER | 8%+ | 15%+ |
| VQV | 40%+ | 60%+ |
| Photo expansion | 15%+ | 25%+ |
| Follow conversion | 0.5%+ | 1%+ |
| Out-of-network | 40%+ | 60%+ |
| Velocity | 40%+ | 60%+ |

---

**Remember**: The algorithm is engagement-driven. Content that triggers diverse engagement gets amplified. Content that doesn't gets buried. Focus on creating valuable, interesting content that sparks likes, retweets, replies, follows, and shares.
