# Dashboard UI Mockup - Multi-Project Social Features

## Main Navigation (Tab Bar)

```
┌─────────────────────────────────────────────────────────────────────┐
│  [📊 Analytics] [📝 Pipeline] [🎯 Strategy] [📱 Profiles] [⚙️ Settings]  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tab 1: 🎯 Content Strategy (NEW)

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🎯 Content Strategy - Draper                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  📄 Current Strategy File: content_plan.md                          │
│  📅 Last Updated: 2026-01-30 10:15                                  │
│                                                                     │
│  ┌────────────────────────────────────┐                            │
│  │ [📤 Upload Markdown] [✏️ Edit in Browser] [📥 Download]         │
│  └────────────────────────────────────┘                            │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ # Draper Marketing Strategy                             │   │
│  │                                                              │   │
│  │ ## Brand Voice                                              │   │
│  │ - Professional but approachable                             │   │
│  │ - Focused on automation and productivity                    │   │
│  │                                                              │   │
│  │ ## Content Pillars                                          │   │
│  │ 1. Marketing Automation Workflows                           │   │
│  │ 2. AI-Powered Content Generation                            │   │
│  │ 3. Behind the Scenes (building in public)                   │   │
│  │                                                              │   │
│  │ ## Posting Guidelines                                       │   │
│  │ - Focus on actionable insights                              │   │
│  │ - Share real examples from our work                         │   │
│  │ - Balance educational + promotional (80/20)                 │   │
│  │                                                              │   │
│  │ [Edit Mode / Preview Mode toggle]                           │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  [💾 Save Changes]  [❌ Discard]                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tab 2: 📱 Social Profiles (NEW)

```
┌─────────────────────────────────────────────────────────────────────┐
│ 📱 Social Profiles - Draper                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Active Profiles for this project:                                 │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ 🐦 Twitter                                                  │    │
│  │ ─────────────────────────────────────────────────────────  │    │
│  │ @acme  [✅ Enabled] [✏️ Edit] [🧪 Test Post]      │    │
│  │ Connected via: Typefully (Draft ID: draft_abc123)          │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ 💼 LinkedIn                                                 │    │
│  │ ─────────────────────────────────────────────────────────  │    │
│  │ Draper Company Page  [✅ Enabled] [✏️ Edit]             │    │
│  │ Connected via: Typefully (Draft ID: draft_xyz789)          │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ ⚡ Nostr                                                     │    │
│  │ ─────────────────────────────────────────────────────────  │    │
│  │ npub1draper... [❌ Disabled] [✏️ Edit]                   │    │
│  │ Direct publishing (no Typefully support)                    │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  [➕ Add New Profile]                                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Add/Edit Profile Modal

```
┌─────────────────────────────────────────────────────────────────┐
│ ✏️ Edit Profile: Twitter @acme                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Platform:      [Twitter ▼]                                    │
│  Handle:        [@acme                   ]           │
│  Display Name:  [Draper                        ]           │
│                                                                 │
│  ─────────────────────────────────────────────────────────     │
│  Publishing Method:                                            │
│  ◉ Typefully                                                   │
│  ○ Direct API                                                  │
│  ○ Manual (drafts only)                                        │
│                                                                 │
│  Typefully Settings:                                           │
│  Draft ID:      [draft_abc123                      ]           │
│  Auto-schedule: [☑ Enabled]                                    │
│                                                                 │
│  ─────────────────────────────────────────────────────────     │
│  Status:                                                       │
│  [✅ Enabled for this project]                                  │
│                                                                 │
│  [💾 Save]  [❌ Cancel]  [🗑️ Delete Profile]                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tab 3: 📅 Posting Strategy (NEW)

```
┌─────────────────────────────────────────────────────────────────────┐
│ 📅 Posting Strategy - Draper                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │ 🌐 Default Strategy (applies to all platforms)            │     │
│  │                                                            │     │
│  │  Frequency:        [Daily ▼]                              │     │
│  │  Posts per day:    [3    ]                                │     │
│  │  Posting times:    [09:00] [14:00] [18:00] [+ Add]        │     │
│  │  Enabled platforms: [☑ Twitter] [☑ LinkedIn] [☐ Nostr]    │     │
│  │                                                            │     │
│  └────────────────────────────────────────────────────────────     │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │ 🐦 Twitter Override (optional)                [▼ Expand]  │     │
│  └───────────────────────────────────────────────────────────┘     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │  Posts per day:    [5    ] (overrides default)            │     │
│  │  Posting times:    [08:00] [12:00] [15:00] [18:00] [21:00]│     │
│  │  Thread ratio:     [30%  ] (30% threads, 70% single posts)│     │
│  │  Max thread length:[5    ] tweets                         │     │
│  │                                                            │     │
│  │  [❌ Clear Override - Use Default]                         │     │
│  └────────────────────────────────────────────────────────────     │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │ 💼 LinkedIn Override (optional)              [▼ Expand]   │     │
│  └───────────────────────────────────────────────────────────┘     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │  Posts per day:    [1    ] (overrides default)            │     │
│  │  Posting times:    [09:00]                                │     │
│  │  Content types:    [☑ Educational] [☑ Case Studies]       │     │
│  │                    [☐ Industry News] [☐ Thought Leadership]│     │
│  │                                                            │     │
│  │  [❌ Clear Override - Use Default]                         │     │
│  └────────────────────────────────────────────────────────────     │
│                                                                     │
│  [💾 Save Strategy]  [🔄 Reset to Defaults]                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tab 4: ⚙️ Integrations (NEW)

```
┌─────────────────────────────────────────────────────────────────────┐
│ ⚙️ Integrations - Draper                                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ 📝 Typefully                                                │    │
│  │ ────────────────────────────────────────────────────────── │    │
│  │                                                             │    │
│  │  Status: [🔴 Not Connected]                                 │    │
│  │                                                             │    │
│  │  API Key:  [•••••••••••••••••••••    ] [👁️ Show]           │    │
│  │            [🔗 Get API Key from Typefully]                  │    │
│  │                                                             │    │
│  │  [🧪 Test Connection]                                       │    │
│  │                                                             │    │
│  │  ─────── Settings ─────────────────────                    │    │
│  │                                                             │    │
│  │  Auto-publish:     [☐ Enable] (use Typefully scheduling)   │    │
│  │  Default schedule: [Morning Batch ▼] (fetch from Typefully)│    │
│  │  Send as drafts:   [☑ Always send as drafts first]         │    │
│  │                                                             │    │
│  │  Connected Accounts: (auto-detected from API)              │    │
│  │  • @acme (Twitter)                               │    │
│  │  • Draper (LinkedIn)                                   │    │
│  │                                                             │    │
│  │  [💾 Save Typefully Settings]                               │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ 🤖 AI Content Generation                                    │    │
│  │ ────────────────────────────────────────────────────────── │    │
│  │                                                             │    │
│  │  Generator: [ZAI GLM-4.7 ▼]                                │    │
│  │             • ZAI GLM-4.7 (current)                         │    │
│  │             • Anthropic Claude                              │    │
│  │             • OpenAI GPT-4                                  │    │
│  │             • Template-based (fallback)                     │    │
│  │                                                             │    │
│  │  [💾 Save]                                                  │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ ⚡ Nostr Relays (optional)                                   │    │
│  │ ────────────────────────────────────────────────────────── │    │
│  │  [+ Add Relay]                                              │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Enhanced Pipeline View (Updated)

```
┌─────────────────────────────────────────────────────────────────────┐
│ 📝 Content Pipeline - Draper                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [🎲 Generate New Content] [🔄 Refresh] [⚙️ Filter]                  │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ ✅ APPROVED                                                 │    │
│  │ ────────────────────────────────────────────────────────── │    │
│  │ "Marketing automation doesn't have to be complicated..."   │    │
│  │                                                             │    │
│  │ 📱 Publishing to:                                           │    │
│  │ [🐦 @acme] [💼 Draper LinkedIn]               │    │
│  │                                                             │    │
│  │ 📅 Scheduled: 2026-01-31 09:00                              │    │
│  │ 🎯 Pillar: Marketing Automation                             │    │
│  │                                                             │    │
│  │ [✏️ Edit] [🗑️ Delete] [📤 Send Now] [⏸️ Pause]               │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ 📝 DRAFT                                                    │    │
│  │ ────────────────────────────────────────────────────────── │    │
│  │ "3 ways AI is changing content creation..."                │    │
│  │                                                             │    │
│  │ 📱 Target profiles:                                         │    │
│  │ [🐦 @acme]                                        │    │
│  │                                                             │    │
│  │ 🤖 Generated by: ZAI GLM-4.7                                │    │
│  │ 🎯 Pillar: AI-Powered Content                               │    │
│  │                                                             │    │
│  │ [👍 Approve] [✏️ Edit] [👎 Reject with feedback]            │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key UI Improvements Summary

1. **🎯 Content Strategy Tab**
   - Upload markdown files
   - Edit in browser
   - Download for backup
   - Version tracking

2. **📱 Social Profiles Tab**
   - Visual cards for each profile
   - Enable/disable toggles
   - Clear connection status
   - Test posting capability
   - Multi-profile support per platform

3. **📅 Posting Strategy Tab**
   - Default strategy (inherited by all)
   - Per-platform overrides
   - Clear inheritance visualization
   - Easy reset to defaults

4. **⚙️ Integrations Tab**
   - Typefully API config
   - Connection testing
   - Account auto-detection
   - Secure key storage
   - AI generator selection

5. **Enhanced Pipeline View**
   - Show which profiles content will post to
   - Platform badges/icons
   - Clear scheduling info
   - Quick actions per content item
