# Multi-Project Automated Content Pipeline Architecture

**System design for automated content generation, review, and learning across multiple projects.**

---

## Overview

The pipeline supports multiple independent projects, each with:
- Separate dashboard views and content queues
- Custom brand voice profiles (`brand_voice.md`)
- Unique content plans (`content_plan.md`)
- Dedicated Typefully accounts
- Independent learning systems

---

## Data Model

### 1. Projects Collection

```json
{
  "project_id": "uuid",
  "name": "Acme",
  "slug": "acme",
  "description": "Confidential AI runtime platform",
  "created_at": "2026-01-29T12:00:00Z",
  "settings": {
    "brand_voice_path": "/projects/acme/brand_voice.md",
    "content_plan_path": "/projects/acme/content_plan.md",
    "typefully_api_key": "typefully_key_XXX",
    "typefully_account_id": "account_XXX",
    "platforms": {
      "linkedin": {
        "enabled": true,
        "account_handle": "@acme"
      },
      "twitter": {
        "enabled": true,
        "account_handle": "@acme"
      },
      "nostr": {
        "enabled": true,
        "public_key": "npub1XXX"
      }
    }
  },
  "generation_schedule": {
    "frequency": "daily",
    "times": ["09:00", "14:00"],
    "posts_per_batch": 5
  }
}
```

### 2. Content Items Collection

```json
{
  "content_id": "uuid",
  "project_id": "uuid",
  "platform": "linkedin|twitter|nostr",
  "content_type": "thread|post|carousel|document",
  "status": "pending_review|approved|needs_work|declined|published",
  "content": {
    "text": "Actual content here...",
    "visual_aids": [
      {
        "type": "gamma_app",
        "url": "https://gamma.app/XXX",
        "thumbnail": "https://gamma.app/XXX/thumb.png"
      }
    ],
    "metadata": {
      "hook_type": "curiosity|value|story|contrarian",
      "pillar": "educational|behind_the_scenes|industry_insights",
      "target_audience": "cto|founder|security_engineer"
    }
  },
  "reasoning": {
    "strategy": "Why this content works",
    "target_audience": "Who this is for",
    "key_points": ["point 1", "point 2"]
  },
  "feedback_history": [
    {
      "timestamp": "2026-01-29T12:00:00Z",
      "from_status": "pending_review",
      "to_status": "needs_work",
      "feedback": "Hook is weak, needs more specificity",
      "learning_tags": ["weak_hook", "generic_opening"]
    }
  ],
  "typefully_draft_id": "draft_XXX",
  "scheduled_for": "2026-01-30T10:00:00Z",
  "published_at": null,
  "created_at": "2026-01-29T12:00:00Z",
  "updated_at": "2026-01-29T12:30:00Z"
}
```

### 3. Learning Patterns Collection

```json
{
  "pattern_id": "uuid",
  "project_id": "uuid",
  "pattern_type": "hook_style|structure|tone|topic|call_to_action",
  "pattern": "Curiosity-driven questions",
  "effectiveness_score": 0.85,
  "sample_size": 42,
  "success_examples": ["content_id_1", "content_id_2"],
  "failure_examples": ["content_id_3"],
  "last_updated": "2026-01-29T12:00:00Z",
  "confidence": "high"
}
```

---

## Content Generation Flow

### Step 1: Scheduled Generation Trigger

```python
# scheduler.py
async def generate_content_for_project(project_id: str):
    project = load_project(project_id)
    brand_voice = load_brand_voice(project.settings.brand_voice_path)
    content_plan = load_content_plan(project.settings.content_plan_path)

    # Determine what to generate based on plan
    weekly_theme = content_plan.get_current_week_theme()

    # Generate batch of content
    for platform in ['linkedin', 'twitter']:
        content_items = await generate_content_batch(
            project=project,
            brand_voice=brand_voice,
            content_plan=content_plan,
            platform=platform,
            weekly_theme=weekly_theme,
            count=project.generation_schedule.posts_per_batch
        )

        # Store in pipeline
        for item in content_items:
            save_content_item(item)
```

### Step 2: Content Generator

```python
# generator/automated_content_generator.py
async def generate_content_batch(
    project: Project,
    brand_voice: BrandVoice,
    content_plan: ContentPlan,
    platform: str,
    weekly_theme: str,
    count: int
) -> List[ContentItem]:

    # Load platform-specific strategy
    strategy = load_platform_strategy(platform)  # linkedin_strategy.md or x_strategy.md

    # Get learning patterns for this project
    patterns = load_learning_patterns(project.project_id)

    # Generate content items
    items = []
    for i in range(count):
        # Select content type based on plan
        content_type = content_plan.get_content_type_for_platform(platform, i)

        # Generate using LLM with context
        content = await llm_generate(
            prompt=f"""
            Generate a {content_type} for {platform}.

            BRAND VOICE:
            {brand_voice.to_string()}

            CONTENT STRATEGY:
            {strategy.to_string()}

            WEEKLY THEME:
            {weekly_theme}

            LEARNING PATTERNS (what works):
            {patterns.to_string()}

            LEARNING PATTERNS (what to avoid):
            {patterns.get_negative_patterns()}
            """,
            project_id=project.project_id,
            platform=platform
        )

        # Generate visual aid if needed
        if content_type in ['carousel', 'document']:
            visual = await generate_visual_with_gamma(content, brand_voice)
            content.visual_aids.append(visual)

        # Store reasoning for learning
        content.reasoning = await generate_reasoning(content, strategy)

        items.append(content)

    return items
```

### Step 3: Visual Aid Generation

```python
# integrations/gamma.py
async def generate_visual_with_gamma(content: ContentItem, brand_voice: BrandVoice):
    prompt = f"""
    Create a visual for this content:

    {content.text}

    Brand style: {brand_voice.visual_guidelines}
    """

    # Call Gamma.app API
    gamma_result = await gamma_api.create_presentation({
        "theme": brand_voice.color_palette,
        "content": extract_key_points(content),
        "style": brand_voice.design_style
    })

    return {
        "type": "gamma_app",
        "url": gamma_result["url"],
        "thumbnail": gamma_result["thumbnail"],
        "embed_code": gamma_result["embed_code"]
    }
```

---

## Review & Feedback Loop

### Dashboard Actions

```python
# dashboard/unified_dashboard.py

@app.post("/pipeline/{content_id}/approve")
async def approve_content(content_id: str):
    content = load_content_item(content_id)

    # 1. Update status
    content.status = "approved"

    # 2. Extract learning patterns
    patterns = extract_learning_patterns(content, status="approved")
    save_learning_patterns(content.project_id, patterns)

    # 3. Send to Typefully
    typefully_draft = await typefully_client.create_draft({
        "content": content.content.text,
        "platform": content.platform,
        "scheduled_for": suggest_best_time(content.platform)
    })
    content.typefully_draft_id = typefully_draft["id"]

    # 4. Save and notify
    save_content_item(content)
    return {"status": "approved", "typefully_draft_id": typefully_draft["id"]}


@app.post("/pipeline/{content_id}/needs-work")
async def request_changes(content_id: str, feedback: str):
    content = load_content_item(content_id)

    # 1. Update status
    content.status = "needs_work"

    # 2. Record feedback
    content.feedback_history.append({
        "timestamp": datetime.now().isoformat(),
        "from_status": "pending_review",
        "to_status": "needs_work",
        "feedback": feedback,
        "learning_tags": extract_negative_tags(feedback)
    })

    # 3. Auto-fix with AI
    fixed_content = await auto_fix_content(content, feedback)

    # 4. Update content with fixes
    content.content = fixed_content.content
    content.status = "pending_review"  # Back to review
    content.feedback_history.append({
        "timestamp": datetime.now().isoformat(),
        "from_status": "needs_work",
        "to_status": "pending_review",
        "feedback": "Auto-fixed based on feedback",
        "auto_fix_applied": True
    })

    save_content_item(content)
    return {"status": "fixed_and_resubmitted"}


@app.post("/pipeline/{content_id}/decline")
async def decline_content(content_id: str, feedback: str):
    content = load_content_item(content_id)

    # 1. Update status
    content.status = "declined"

    # 2. Record feedback
    content.feedback_history.append({
        "timestamp": datetime.now().isoformat(),
        "from_status": "pending_review",
        "to_status": "declined",
        "feedback": feedback,
        "learning_tags": extract_negative_tags(feedback)
    })

    # 3. Extract negative patterns for learning
    negative_patterns = extract_negative_patterns(content, feedback)
    save_negative_patterns(content.project_id, negative_patterns)

    save_content_item(content)
    return {"status": "declined", "patterns_learned": len(negative_patterns)}
```

### Auto-Fix Logic

```python
# generator/auto_fix.py
async def auto_fix_content(content: ContentItem, feedback: str):
    """
    Use AI to fix content based on feedback.
    """
    project = load_project(content.project_id)
    brand_voice = load_brand_voice(project.settings.brand_voice_path)

    fixed = await llm_fix(f"""
    ORIGINAL CONTENT:
    {content.content.text}

    FEEDBACK:
    {feedback}

    BRAND VOICE:
    {brand_voice.to_string()}

    Please rewrite the content to address the feedback while maintaining the brand voice.
    Output only the fixed content.
    """)

    content.content.text = fixed
    return content
```

---

## Learning System

### Pattern Extraction

```python
# learning/pattern_extractor.py

def extract_learning_patterns(content: ContentItem, status: str) -> List[LearningPattern]:
    """
    Extract patterns from approved or declined content.
    """
    patterns = []

    if status == "approved":
        # What worked
        patterns.append({
            "pattern_type": "hook_style",
            "pattern": extract_hook_style(content.content.text),
            "effectiveness_score": 1.0,
            "success_examples": [content.content_id]
        })

        patterns.append({
            "pattern_type": "structure",
            "pattern": extract_structure(content.content.text),
            "effectiveness_score": 1.0,
            "success_examples": [content.content_id]
        })

    elif status == "declined":
        # What didn't work
        feedback = content.feedback_history[-1]["feedback"]
        patterns.append({
            "pattern_type": "negative_pattern",
            "pattern": extract_pattern_from_feedback(feedback),
            "effectiveness_score": 0.0,
            "failure_examples": [content.content_id]
        })

    return patterns


def extract_hook_style(text: str) -> str:
    """Extract the hook pattern from content."""
    first_line = text.split('\n')[0]

    if '?' in first_line:
        return "question_hook"
    elif any(word in first_line.lower() for word in ['unpopular', 'controversial', 'wrong']):
        return "contrarian_hook"
    elif any(char.isdigit() for char in first_line):
        return "number_hook"
    else:
        return "statement_hook"
```

### Learning Application

```python
# learning/pattern_applier.py

def get_learning_context(project_id: str) -> str:
    """
    Compile learning patterns into context for content generation.
    """
    patterns = load_learning_patterns(project_id)

    positive = "\n".join([
        f"✓ {p.pattern} (effectiveness: {p.effectiveness_score:.0%})"
        for p in patterns if p.effectiveness_score > 0.7
    ])

    negative = "\n".join([
        f"✗ {p.pattern} (avoid this)"
        for p in patterns if p.effectiveness_score < 0.3
    ])

    return f"""
    WHAT WORKS FOR THIS BRAND:
    {positive}

    WHAT TO AVOID:
    {negative}
    """
```

---

## Typefully Integration

### API Client

```python
# integrations/typefully.py

class TypefullyClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.typefully.io/v1"

    async def create_draft(self, content: dict) -> dict:
        """
        Create a draft in Typefully for scheduling.
        """
        response = await http_post(
            f"{self.base_url}/drafts",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "content": content["content"],
                "platform": content["platform"],  # "linkedin" or "twitter"
                "scheduled_for": content.get("scheduled_for"),
                "thread": content.get("is_thread", False),
                "media": content.get("visual_aids", [])
            }
        )

        return {
            "id": response["id"],
            "edit_url": response["edit_url"],
            "status": "draft"
        }

    async def get_draft_status(self, draft_id: str) -> dict:
        """Check if draft has been scheduled/published."""
        response = await http_get(
            f"{self.base_url}/drafts/{draft_id}",
            headers={"Authorization": f"Bearer {self.api_key}"}
        )

        return {
            "status": response["status"],  # "draft", "scheduled", "published"
            "scheduled_for": response.get("scheduled_for"),
            "published_at": response.get("published_at"),
            "url": response.get("url")
        }
```

---

## Dashboard UI Updates

### Project Switcher

```html
<!-- Top of dashboard -->
<div class="project-switcher">
    <select id="project-select" onchange="switchProject(this.value)">
        <option value="">Select Project...</option>
        {% for project in projects %}
        <option value="{{ project.id }}"
                {% if project.id == current_project.id %}selected{% endif %}>
            {{ project.name }}
        </option>
        {% endfor %}
    </select>
    <button onclick="showCreateProjectModal()">+ New Project</button>
</div>

<script>
function switchProject(projectId) {
    window.location.href = `/?project=${projectId}&tab=pipeline`;
}
</script>
```

### Pipeline Tab with Three-State Actions

```html
<!-- For each content item -->
<div class="content-card">
    <div class="content">{{ content.content.text }}</div>

    {% if content.visual_aids %}
    <div class="visual-aids">
        {% for visual in content.visual_aids %}
        <img src="{{ visual.thumbnail }}" alt="Visual aid">
        {% endfor %}
    </div>
    {% endif %}

    <div class="actions">
        <!-- Approve: Send to Typefully -->
        <form method="POST" action="/pipeline/{{ content.content_id }}/approve">
            <button type="submit" class="btn-success">✓ Approve & Schedule</button>
        </form>

        <!-- Needs Work: Request feedback + auto-fix -->
        <form method="POST" action="/pipeline/{{ content.content_id }}/needs-work"
              onsubmit="showFeedbackModal(event, '{{ content.content_id }}')">
            <textarea name="feedback" placeholder="What needs work?" required></textarea>
            <button type="submit" class="btn-warning">↻ Fix & Resubmit</button>
        </form>

        <!-- Decline: Mark as bad example -->
        <form method="POST" action="/pipeline/{{ content.content_id }}/decline"
              onsubmit="showDeclineModal(event, '{{ content.content_id }}')">
            <textarea name="feedback" placeholder="Why declined? (for learning)"></textarea>
            <button type="submit" class="btn-danger">✗ Decline</button>
        </form>
    </div>

    {% if content.feedback_history %}
    <div class="feedback-history">
        <h4>Feedback History</h4>
        {% for feedback in content.feedback_history %}
        <div class="feedback-item">
            <span class="badge badge-{{ feedback.to_status }}">
                {{ feedback.to_status|title }}
            </span>
            <span class="timestamp">{{ feedback.timestamp }}</span>
            <p>{{ feedback.feedback }}</p>
            {% if feedback.learning_tags %}
            <div class="learning-tags">
                {% for tag in feedback.learning_tags %}
                <span class="tag">{{ tag }}</span>
                {% endfor %}
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% endif %}
</div>
```

---

## Implementation Phases

### Phase 1: Data Model & Storage (Foundation)
- Create projects schema
- Migrate existing content to new schema
- Add project switching to dashboard

### Phase 2: Automated Generation
- Build content generator using strategies
- Add Gamma.app integration
- Implement scheduled generation

### Phase 3: Three-State Workflow
- Implement approve/needs-work/decline actions
- Build auto-fix system
- Add feedback history tracking

### Phase 4: Learning System
- Extract patterns from feedback
- Build pattern storage and retrieval
- Apply learning to generation

### Phase 5: Typefully Integration
- Create Typefully client
- Implement draft creation
- Track published content

### Phase 6: Dashboard Enhancements
- Project management UI
- Per-project analytics
- Learning insights dashboard

---

## File Structure

```
draper-pipeline/
├── projects/
│   ├── acme/
│   │   ├── brand_voice.md
│   │   ├── content_plan.md
│   │   └── learning_patterns.json
│   ├── draper/
│   │   ├── brand_voice.md
│   │   ├── content_plan.md
│   │   └── learning_patterns.json
│   └── {project_slug}/
│       ├── brand_voice.md
│       ├── content_plan.md
│       └── learning_patterns.json
├── data/
│   ├── projects.json          # Project metadata
│   ├── content_items.json     # All content across projects
│   └── learning_patterns.json # Cross-project learning (optional)
├── generator/
│   ├── automated_content_generator.py
│   ├── auto_fix.py
│   └── pattern_extractor.py
├── integrations/
│   ├── typefully.py
│   └── gamma.py
├── learning/
│   ├── pattern_extractor.py
│   ├── pattern_storage.py
│   └── pattern_applier.py
└── dashboard/
    ├── unified_dashboard.py   # Add project context
    └── templates/
        ├── unified.html        # Add project switcher
        └── project_management.html
```

---

## Environment Variables

```bash
# Typefully API (per project or global)
TYPEFULLY_API_KEY=sk_live_XXX

# Gamma.app API
GAMMA_APP_API_KEY=gamma_XXX

# Content Generation
GENERATION_SCHEDULE_ENABLED=true
GENERATION_TIMES=09:00,14:00
DEFAULT_BATCH_SIZE=5
```

---

## Next Steps

1. **Review and approve architecture** - Does this match your vision?
2. **Prioritize phases** - Which phase should we implement first?
3. **Define Typefully API scope** - What Typefully features do we need?
4. **Set up Acme as pilot project** - Create acme brand_voice.md and content_plan.md
