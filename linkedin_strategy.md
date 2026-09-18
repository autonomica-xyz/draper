# Draper LinkedIn Strategy: Human-First Content

**Platform Psychology: LinkedIn is where professionals go to learn, not be sold to.**

---

## Executive Summary

LinkedIn works for Draper because:
- Decision-makers hang out here (founders, CTOs, engineering managers)
- The algorithm rewards thoughtful, substantive content
- Technical depth is valued over quick hot takes
- Document posts and newsletters get massive reach
- B2B purchasing decisions are researched here

**The trap**: Most companies treat LinkedIn like a promotional bulletin board. That doesn't work anymore.

---

## Tone: The "Smart Colleague" Voice

### What This Means

You're not talking *at* professionals. You're talking *with* them. Like a smart colleague who figured something out and wants to share.

**Personality traits**:
- Curious but not clueless
- Confident but not arrogant
- Technical but accessible
- Transparent about failures
- Opinionated but open to being wrong

**Voice rules**:
- Write like you speak (remove corporate jargon)
- Use "I" and "we" (first person is honest)
- Vary sentence length (short. long. medium.)
- Admit uncertainty ("I'm still figuring this out")
- Show emotion (frustration, excitement, surprise)

### Examples

**Bad (AI-sounding corporate speak)**:
> "We are thrilled to announce groundbreaking capabilities that revolutionize the autonomous agent landscape, underscoring our commitment to excellence."

**Good (human colleague)**:
> "I've been wrestling with agent memory for three months. Yesterday I finally figured out what was wrong. Here's the fix."

---

## Anti-Patterns: What Makes LinkedIn Posts Look Like AI

### 1. Generic Motivational Content

**AI pattern**: Inspirational quotes about "hard work" and "grinding" with zero substance

**Avoid**:
- "Success is not final, failure is not fatal"
- "The only way to do great work is to love what you do"
- Any quote from Einstein, Jobs, or Musk without context

**Instead**: Share something real you learned this week. Even if it's small.

### 2. The "Story ≠ Lesson" Formula

**AI pattern**: Personal story that inevitably leads to a generic business lesson

**Formula AI uses**:
```
I faced [challenge]
Through perseverance, I overcame it
The lesson: [generic platitude about never giving up]
```

**Why this fails**: Real stories don't wrap up neatly. Real learning is messy.

**Instead**: Share the story without forcing a lesson. Or share the lesson and admit you're still figuring it out.

### 3. Over-Structuring with Emojis

**AI pattern**: Every post uses the same emoji headers

**Avoid**:
```
🚀 The Problem
💡 The Solution
✅ The Result
🔥 Key Takeaway
```

**Why this fails**: Real people don't format their thoughts like bullet-point memos.

**Instead**: Use formatting sparingly. A single bold header. Or no formatting at all—just good writing.

### 4. Engagements Bait

**AI pattern**: Questions designed solely for comments, not genuine discussion

**Avoid**:
- "What's your biggest challenge with AI? Let me know below!"
- "Agree or disagree? Share your thoughts!"
- "Tag someone who needs to see this!"

**Why this fails**: People can smell the engagement bait.

**Instead**: End with a genuine question you actually want answered. Or no question at all—sometimes strong content speaks for itself.

### 5. The "Humble Brag" Disguised as Vulnerability

**AI pattern**: Supposedly admitting weakness while actually showing off

**Avoid**:
- "I used to work 100 hour weeks until I realized efficiency matters more"
- "We turned down a $5M offer because we believe in our mission"

**Why this fails**: It's transparently performative.

**Instead**: Real vulnerability—admit a mistake, share a failure, acknowledge what you don't know.

### 6. Overuse of AI Vocabulary Words

**AI words to avoid**:
- Additionally
- Underscore
- Showcase
- Pivotal
- Crucial
- Landscape
- Testament
- Foster
- Enhance

**Instead**: Use normal words
- Additionally → Also / Plus
- Underscore → Show / Highlight
- Showcase → Share / Show
- Pivotal → Important
- Crucial → Key
- Landscape → Space / Field
- Testament → Proof
- Foster → Build
- Enhance → Improve

---

## Content That Works: Proven Formats

### Format 1: The "Building in Public" Update

**Why it works**: Transparency builds trust. People follow journeys, not announcements.

**Structure**:
```
[Hook: Unexpected result or problem]

[Context: What happened]

[The technical details]

[What you learned]

[What's next]

[Optional: Question for discussion]
```

**Real example**:
```
Week 8 of building our AI-operated business and I just deleted 40% of our code.

Here's what happened:

We built a multi-agent system for customer support. Looked great on paper.

Reality: The agents kept arguing with each other. Literally.

Agent A would promise a refund. Agent B would deny it two minutes later.
Customers were confused. We were confused.

I spent Sunday digging through logs. The problem?

We didn't need multi-agent for this. Single agent with good tool calling
handled 95% of cases. The other 5%? Those should escalate to humans anyway.

So I deleted the multi-agent architecture. 2,400 lines gone.

Customers are happier. Response times are down. Our LLM bill is cut in half.

The lesson I keep relearning: Simple beats clever. Every time.

Anyone else fallen into the "over-engineering because it's interesting" trap?
```

**Why this works**:
- Specific numbers (Week 8, 40%, 2,400 lines)
- Honest about the mistake
- Technical but accessible
- Real lesson, not a platitude
- Genuine question at the end

### Format 2: The Technical Deep-Dive

**Why it works**: LinkedIn rewards substantive content. Technical depth builds authority.

**Structure**:
```
[Hook: Counterintuitive finding or strong opinion]

[The conventional wisdom]

[Why it's wrong (with data)]

[What actually works (with implementation details)]

[Results]

[Optional: Framework or mental model]
```

**Real example**:
```
Unpopular opinion: You don't need a vector database for most RAG use cases.

Everyone's jumping on Pinecone, Weaviate, Qdrant. I get why—the tech is cool.

But for 80% of companies, you're over-engineering.

Here's what we've learned from testing:

We built our agent memory system three ways:

1. Full conversation history (expensive, slow)
2. Vector DB with semantic search (complex, fragile)
3. Simple keyword search + summary caching (boring, fast)

Guess which won?

Option 3.

Here's why:

• Keyword search handles 90% of "what did we discuss about X?" queries
• Summary caching reduces tokens by 85% vs. full history
• Setup takes 2 hours, not 2 weeks
• Zero maintenance vs. "why is the embedding server down again"

Vector databases have their place. But start simple. Add complexity when you
earn it, not before.

The framework I use: Can I solve this with a hash map?

If yes, do that first.
```

**Why this works**:
- Strong contrarian take
- Backed by actual testing
- Specific percentages
- Actionable framework at the end
- Technical but readable

### Format 3: The "Behind the Scenes" Story

**Why it works**: People love seeing how the sausage is made.

**Structure**:
```
[Hook: Surprising moment or decision]

[Set the scene]

[The decision to be made]

[How you decided]

[What happened]

[What you'd do differently]
```

**Real example**:
```
Last month our AI support agent offered a customer a 50% discount that doesn't exist.

We laughed about it. Then we panicked.

That one hallucination could have cost us real money if the customer accepted.

Here's how we fixed it:

We started with negative constraints: "Never offer discounts not in the database."

That didn't work. LLMs are creative. They found ways around it.

Then we tried validation: After every response, check for prohibited actions.

Better, but added 200ms latency. Customers noticed.

Finally—solution that stuck:

We moved the constraints into the tool definitions themselves.

The "offer_discount" tool now has:
{
  "valid_discounts": [10, 15, 20],
  "requires_approval": 15,
  "max_monthly": 5
}

The agent can't offer a 50% discount because the tool literally won't accept it.

Zero hallucinations since deployment. And we actually sleep at night.

The insight: Fix at the architecture layer, not the prompt layer.
```

**Why this works**:
- Starts with a funny but scary moment
- Shows multiple attempts (real engineering process)
- Technical but narrative
- Clear insight at the end

### Format 4: Document Posts (Carousels)

**Why it works**: LinkedIn's algorithm heavily promotes document posts. People save them for reference.

**How to do it right**:

**Don't**:
- Stuff 20 points into a 10-slide deck
- Use generic business stock photos
- Copy-paste text from ChatGPT
- Make every slide look the same

**Do**:
- One clear idea per slide
- Minimal text (people zoom in to read)
- Visual hierarchy (big number, explanation, example)
- Varied layouts (some slides have diagrams, some text, some code)
- Add personality to the design

**Slide structure for "7 Agent Failure Modes"**:

Slide 1: Hook
```
7 Ways Our Agents Failed
(And How We Fixed Them)

[Your name/brand]
```

Slide 2: Problem 1
```
1. The Hallucination Loop

What happened:
Agent makes up something → stores it → retrieves it later → reinforces the lie

Example: Our support agent invented a "Pro plan" feature that doesn't exist.
Three customers asked about it the next day.

Fix: Validate facts before storage. Use citations. Fact-check outputs.
```

Slide 3: Problem 2
```
2. The Infinite Tool Call

What happened:
Agent gets stuck calling the same tool in a loop. 47 times in one second.

Example: Customer asked "is my refund ready?" Agent checked status 47 times
before we killed the process.

Fix: Add max iteration limits. Monitor for loops. Kill after 3 redundant calls.
```

[Continue for all 7...]

Slide 10: Summary + CTA
```
Full breakdown with code examples on our blog.

[Link in comments]

What's the weirdest agent behavior you've encountered?
```

**Why this works**:
- Scannable (people can zoom in on what interests them)
- Saveable (people bookmark these for reference)
- Shareable (easy to screenshot individual slides)
- Not promotional (pure value)

---

## Posting Strategy: Rhythm Over Virality

### Weekly Cadence

**Monday**: AI-Operated Business update (weekly metrics + learning)
**Tuesday**: Technical deep-dive or framework
**Wednesday**: Engagement day (comment on others' posts)
**Thursday**: Behind-the-scenes story or opinion
**Friday**: Interesting finding or industry commentary

**Volume**: 3-4 posts per week. Quality over quantity.

### Timing

**Best times** (US audience):
- 7:00-8:00am PST (before work)
- 12:00-1:00pm PST (lunch)
- 5:00-6:00pm PST (after work)

**Rule**: Better to post at the wrong time than skip posting. Consistency beats optimization.

### Engagement: The 1-Hour Rule

**Critical**: The first hour after posting determines 80% of your reach.

**What to do in that first hour**:
- Reply to every comment within 5 minutes
- Add value in responses (not "thanks!")
- Ask follow-up questions to keep threads going
- Share the post in relevant communities (Discord, etc.)

**After the first hour**: Continue responding, but urgency drops off.

### Commenting Strategy (Growth Hack)

**Principle**: Your comments on others' posts build your following faster than your own posts.

**Daily routine** (15-20 minutes):
1. Identify 10 target accounts (AI researchers, founders, developers)
2. Turn on notifications for their posts
3. When they post, comment quickly (first hour = visibility)
4. Add actual value, not "great post!"

**Good comment formula**:
```
[Validation: "Interesting point about X"]

[Your experience: "We found the opposite when we tried Y"]

[Question: "Curious if you've seen Z affect this?"]
```

**Example**:
```
Interesting point about multi-agent systems. We actually found single agents
with good tool calling handle 80% of use cases better. Multi-agent shines for
truly independent decision-making.

Curious if you've hit issues with agent coordination overhead? We kept running
into agents working at cross-purposes.
```

**Why this works**:
- Shows expertise without being promotional
- Starts conversations
- Gets you seen by their audience
- Builds relationships with key people

---

## LinkedIn Newsletter: Force Multiplier

**Why newsletters matter**: LinkedIn notifies ALL followers when you publish a newsletter post. This is the only way to guarantee your entire audience sees your content.

### Newsletter Strategy

**Frequency**: Bi-weekly (every other Thursday)
**Format**: "AI-Operated Business Update"
**Length**: 500-800 words
**Sections**:

1. **Metrics this week** (data builds credibility)
2. **What broke** (vulnerability builds trust)
3. **Technical deep-dive** (substance builds authority)
4. **Something interesting** (curiosity builds engagement)
5. **Community spotlight** (sharing builds reciprocity)

**Sample outline**:
```
AI-Operated Business: Week 12

This week our agents made 9,247 autonomous decisions.
Only 8 required human intervention (0.09%).

Here's what went wrong, what I learned, and something interesting.

### What Broke

Our support agent started hallucinating discount codes again.

[Story + technical fix + lesson]

### Technical Deep-Dive: Agent Memory Systems

I've spent the last month testing different approaches to agent memory.

[Detailed technical breakdown with code]

### Something Interesting

Gartner predicts 40% of agentic AI projects will be canceled by 2027.

[My take + data + what this means for builders]

### Community Spotlight

This week: @username built [cool thing] using Draper

[Showcase their work]

See you in two weeks.
[Your name]
```

**Why this works**:
- Not promotional (zero "buy our product")
- High signal-to-noise ratio
- Shows, doesn't tell
- Builds audience over time

---

## Metrics That Matter

### Vanity Metrics (Ignore These)
- Total follower count
- Total impressions
- "Virality" score

### Real Metrics (Track These)
- **Engagement rate**: (likes + comments + shares) / impressions
  - Good: 5%+
  - Great: 10%+
- **Comment quality**: Are people having real discussions?
- **Follower growth**: 50-100/week is healthy
- **Profile views**: Track weekly—indicates interest
- **Connection requests**: From relevant people (target accounts)

### Weekly Review Questions

1. Which post had the highest engagement rate? Why?
2. Which comments led to real conversations?
3. What topics resonated? What flopped?
4. Did we get any inbound leads from content?
5. What feedback did we get? (positive or negative)

---

## What "AI Slop" Looks Like on LinkedIn

### Red Flags

Your content looks like AI if:
- Every post uses the same structure (hook → points → takeaway)
- All headers are bolded with emojis
- You never show real data or numbers
- The "lessons" are always generic ("never give up")
- Comments are superficial ("great insights!")
- There's no personality or voice

### The Mirror Test

**Before posting, ask**: Would I say this to a colleague over coffee?

If the answer is "no" or "I'd sound ridiculous," don't post it.

**Real test**: Read your post aloud. Does it sound like you? Or does it sound like LinkedIn Article Generator 3000?

---

## Execution Checklist

### Before Posting
- [ ] Read post aloud—does it sound like me?
- [ ] Check for AI vocabulary words (showcase, underscore, pivotal)
- [ ] Remove unnecessary formatting (emojis, bold headers)
- [ ] Verify claims have actual numbers/data
- [ ] Add personality (opinion, humor, uncertainty)
- [ ] End with genuine question OR no question (never force it)

### After Posting (First Hour)
- [ ] Reply to every comment within 5 minutes
- [ ] Add value in responses, not just "thanks!"
- [ ] Ask follow-up questions to keep threads alive
- [ ] Share to Discord/community if relevant

### Weekly
- [ ] Review top and bottom performing posts
- [ ] Note which topics resonated
- [ ] Identify AI patterns that crept in
- [ ] Adjust strategy based on data

---

## Sample 30-Day Content Calendar

**Week 1: Foundation**
- Mon: "Why we're building an AI-operated business" (origin story)
- Tue: Technical deep-dive: "Our agent architecture"
- Thu: "The week we broke production" (failure story)
- Fri: "Multi-agent vs. single-agent" (opinion piece)

**Week 2: Transparency**
- Mon: AI-Operated Business Week 2 update (metrics)
- Tue: "How we reduced LLM costs by 73%" (technical)
- Thu: "I was wrong about vector databases" (admission)
- Fri: "7 tools every AI engineer should know" (resource list)

**Week 3: Community**
- Mon: AI-Operated Business Week 3 update (metrics)
- Tue: Document post: "Agent failure modes" (carousel)
- Thu: Community spotlight: "Look what @user built"
- Fri: "The future of autonomous agents" (speculation)

**Week 4: Lessons**
- Mon: AI-Operated Business Week 4 update (metrics)
- Tue: "What I learned from 4 weeks of AI operations"
- Thu: "Our best investment wasn't technology" (surprise)
- Fri: Monthly recap: "Month 1 by the numbers"

---

## Final Thoughts

**The secret**: LinkedIn rewards substance and consistency, not tricks and hacks.

Your goal isn't to "go viral." Your goal is to become the person people follow because you consistently share useful, interesting, honest content about building AI-operated businesses.

**The paradox**: The less you try to sound like an expert, the more people perceive you as one.

Admit what you don't know. Share what went wrong. Be transparent about your process. Real expertise has nothing to prove.

---

*This strategy document emphasizes human-first content over AI-generated patterns. For templates and swipe files, see the main Draper marketing plan.*
