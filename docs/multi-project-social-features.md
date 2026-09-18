# Multi-Project Social Features - Design Doc

**Date:** 2026-01-30  
**Status:** Planning  
**Context:** Draper enhancement

## Current State
- ✅ Multi-project support exists (draper, acme)
- ✅ Project switching works
- ✅ Per-project content pipeline (reviews.json)
- ⚠️ Content plans are hardcoded markdown files (acme.md, etc.)
- ⚠️ No UI for uploading/editing content strategy
- ⚠️ Typefully API key stored in .env (global, not per-project)
- ⚠️ No social profile mapping (one account per platform)

## Requirements

### 1. Markdown Content Plan Upload/Edit Per Project
**What:** Each project should have its own content strategy/plan uploaded via dashboard as markdown files.

**UI Flow:**
- Dashboard tab: "Content Strategy" (per project)
- Upload markdown file OR edit in browser textarea
- Store in: `data/projects/{project_id}/content_plan.md`
- Load this when generating content for the project

**Implementation:**
- Add upload endpoint: `POST /projects/{project_id}/content-plan/upload`
- Add edit endpoint: `POST /projects/{project_id}/content-plan/save`
- Add download endpoint: `GET /projects/{project_id}/content-plan/download`
- Update `ProjectSettings.content_plan_path` to point to project file

### 2. Platform Posting Strategy Per Project
**What:** Each project can have different posting strategies (default + overrides).

**Config Structure:**
```json
{
  "project_id": "draper-fc78f02c",
  "posting_strategy": {
    "default": {
      "frequency": "daily",
      "posts_per_day": 3,
      "times": ["09:00", "14:00", "18:00"],
      "platforms": ["twitter", "linkedin"]
    },
    "twitter": {
      "posts_per_day": 5,
      "times": ["08:00", "12:00", "15:00", "18:00", "21:00"],
      "thread_vs_single_ratio": 0.3
    },
    "linkedin": {
      "posts_per_day": 1,
      "times": ["09:00"],
      "content_types": ["educational", "case_studies"]
    }
  }
}
```

**UI:**
- Tab: "Posting Strategy"
- Default strategy form (applies to all platforms)
- Per-platform overrides (collapsible sections)
- Save/Reset buttons

### 3. Typefully API Configuration in Dashboard
**What:** Configure Typefully API keys per project in the UI (not .env).

**Current:**
- Typefully API key in `.env` file (global)
- Not project-specific

**Needed:**
```json
{
  "project_id": "draper-fc78f02c",
  "integrations": {
    "typefully": {
      "api_key": "tf_...",
      "drafts_enabled": true,
      "auto_schedule": false,
      "default_schedule_id": "sch_abc123"
    }
  }
}
```

**UI:**
- Tab: "Integrations" > Typefully section
- API Key input (masked)
- Test connection button
- Schedule dropdown (fetch from Typefully API)
- Enable/disable drafts
- Enable/disable auto-scheduling

**Security:**
- Store API keys in `data/projects/{project_id}/secrets.json` (gitignored)
- Load at runtime, never expose in responses

### 4. Social Sets Selection Per Project
**What:** Select which social profiles/accounts to post to per project.

**Concept:** "Social Set" = a collection of social accounts
- Example: Personal brand set (personal Twitter + LinkedIn)
- Example: Draper brand set (Draper Twitter + Draper LinkedIn + Draper Nostr)
- Example: Acme brand set (Acme Twitter + Acme LinkedIn)

**UI:**
- Tab: "Social Profiles"
- List of available sets (global config)
- Checkboxes to enable for this project
- Or: Custom set builder (select individual accounts)

**Implementation:**
- Global: `data/social_sets.json` (all available accounts)
- Per-project: `settings.enabled_social_sets: ["brand", "personal"]`

### 5. Multiple Social Profiles Per Project (Clear Mapping)
**What:** Support multiple accounts per platform with clear UI indication.

**Example:**
- Draper project → posts to:
  - Twitter: @acme
  - LinkedIn: Draper Company Page
  - Nostr: npub1draper...
  
- Personal project → posts to:
  - Twitter: @founder
  - LinkedIn: Personal Founder Account

**Data Model:**
```json
{
  "project_id": "draper-fc78f02c",
  "social_profiles": [
    {
      "platform": "twitter",
      "profile_id": "twitter_draper",
      "handle": "@acme",
      "display_name": "Draper",
      "enabled": true,
      "typefully_draft_id": "draft_abc123"
    },
    {
      "platform": "linkedin",
      "profile_id": "linkedin_draper_company",
      "handle": "draper-xyz",
      "display_name": "Draper",
      "enabled": true,
      "typefully_draft_id": null
    },
    {
      "platform": "nostr",
      "profile_id": "nostr_draper",
      "npub": "npub1...",
      "display_name": "Draper",
      "enabled": true
    }
  ]
}
```

**UI:**
- Tab: "Social Profiles"
- Table/cards showing each profile:
  - Platform icon + name
  - Handle/npub
  - Enabled toggle
  - Edit/Configure button
  - Test post button
- Add new profile button

**Dashboard Display:**
- Content item shows which profiles it's scheduled for
- Icons/badges for each platform
- Click to see profile details

## Implementation Plan

### Phase 1: Content Plan Upload (Quick Win)
1. Add upload/edit endpoints for markdown
2. Add UI tab for content strategy
3. Update content generator to read from project-specific file

### Phase 2: Social Profiles Management
1. Add `social_profiles` to project data model
2. Create social profiles UI (add/edit/delete)
3. Update content items to track destination profiles
4. Display profile badges in dashboard

### Phase 3: Posting Strategy UI
1. Add posting strategy config to project settings
2. Create strategy editor UI
3. Default + per-platform overrides
4. Validate and save

### Phase 4: Typefully Integration Config
1. Add Typefully config section to project settings
2. Create integrations UI tab
3. Store API keys securely
4. Test connection + fetch schedules
5. Map profiles to Typefully drafts

### Phase 5: Social Sets (Optional/Later)
1. Define social sets concept
2. Allow quick enabling of predefined sets
3. UI for managing sets globally

## File Structure

```
data/
├── projects.json                          # All projects metadata
├── social_sets.json                       # Global social sets (optional)
├── projects/
│   ├── draper-fc78f02c/
│   │   ├── content_plan.md               # ← NEW: Uploaded content strategy
│   │   ├── reviews.json                  # Content pipeline
│   │   ├── secrets.json                  # ← NEW: API keys (gitignored)
│   │   └── settings.json                 # ← NEW: Project settings (strategies, profiles)
│   └── acme-a1b2c3d4/
│       ├── content_plan.md
│       ├── reviews.json
│       ├── secrets.json
│       └── settings.json
```

## Questions to Resolve

1. **Social sets vs. individual profile selection?**
   - Should we have predefined sets, or just allow selecting individual profiles?
   - Recommendation: Start with individual profiles, add sets later if needed

2. **Typefully profile mapping**
   - How to map our "social profiles" to Typefully draft accounts?
   - Can we fetch available accounts from Typefully API?
   - Recommendation: Let user select/map manually in UI

3. **Multi-account posting**
   - Should one content item post to multiple profiles on same platform?
   - Example: Post same content to @founder AND @acme on Twitter
   - Recommendation: Yes, support this. Content can go to multiple profiles.

4. **Default posting strategy inheritance**
   - Should platform-specific strategies inherit from default and override?
   - Recommendation: Yes, merge default + platform override

## Next Steps

1. **Review this design** with the team
2. **Pick Phase 1** (content plan upload) to start
3. **Build incrementally** - ship each phase separately
4. **Test with Draper** project first
