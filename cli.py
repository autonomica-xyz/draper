#!/usr/bin/env python3
"""
Draper Marketing Pipeline CLI

A fully automated AI-powered content generation and scheduling system.
Supports multiple projects with strict isolation.

Usage:
    draper project list
    draper project add <name> [--typefully-key KEY]
    draper project switch <name>
    draper project config [--set KEY=VALUE]
    
    draper generate [--count N] [--platform twitter|linkedin|both]
    draper status
    draper review [--web] [--port PORT]
    draper schedule
    
    draper config
"""

import argparse
import json
import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent))


def get_data_dir() -> Path:
    """Get data directory, creating if needed"""
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_project_manager():
    """Get project manager instance"""
    from projects import ProjectManager
    return ProjectManager(data_dir=str(get_data_dir()))


def show_current_project():
    """Show current project context"""
    pm = get_project_manager()
    project = pm.get_current_project()
    if project:
        has_typefully = "✅" if project.has_typefully_configured() else "❌"
        print(f"📁 Project: {project.name} ({project.project_id})")
        print(f"   Typefully: {has_typefully}")
    else:
        print("⚠️  No project selected. Use 'draper project switch <name>'")


# =============================================================================
# Project Commands
# =============================================================================

def cmd_project_list(args):
    """List all projects"""
    pm = get_project_manager()
    projects = pm.list_projects()
    current_id = pm.get_current_project_id()

    if not projects:
        print("\n📁 No projects configured")
        print("   Create one with: draper project add <name>")
        return 0

    print(f"\n📁 Projects ({len(projects)})")
    print("=" * 60)

    for p in projects:
        marker = "→ " if p.project_id == current_id else "  "
        typefully = "✅" if p.has_typefully_configured() else "❌"
        platforms = ", ".join(p.config.platforms)

        print(f"{marker}{p.name}")
        print(f"     ID: {p.project_id}")
        print(f"     Typefully: {typefully}  Platforms: {platforms}")
        if p.description:
            print(f"     {p.description}")
        print()

    return 0


def cmd_project_add(args):
    """Add a new project"""
    pm = get_project_manager()

    try:
        project = pm.create_project(
            name=args.name,
            description=args.description or "",
            typefully_api_key=args.typefully_key,
            platforms=args.platforms.split(",") if args.platforms else ["twitter", "linkedin"]
        )

        print(f"\n✅ Created project: {project.name}")
        print(f"   ID: {project.project_id}")

        if not project.has_typefully_configured():
            print("\n⚠️  Typefully not configured. Add with:")
            print("   draper project config --set typefully_api_key=YOUR_KEY")

        # Auto-switch to new project
        pm.set_current_project(project.project_id)
        print(f"\n→ Switched to project: {project.name}")

        return 0

    except ValueError as e:
        print(f"❌ {e}")
        return 1


def cmd_project_switch(args):
    """Switch to a different project"""
    pm = get_project_manager()

    # Try by name first, then by ID
    project = pm.get_project_by_name(args.name)
    if not project:
        project = pm.get_project(args.name)

    if not project:
        print(f"❌ Project not found: {args.name}")
        print("   Use 'draper project list' to see available projects")
        return 1

    pm.set_current_project(project.project_id)
    print(f"→ Switched to project: {project.name}")

    if not project.has_typefully_configured():
        print("⚠️  Typefully not configured for this project")

    return 0


def cmd_project_config(args):
    """Show or update project configuration"""
    pm = get_project_manager()
    project = pm.get_current_project()

    if not project:
        print("❌ No project selected")
        print("   Use 'draper project switch <name>' first")
        return 1

    if args.set:
        # Update config
        key, value = args.set.split("=", 1)

        # Handle list values
        if key in ["platforms", "pillars", "brand_keywords", "schedule_times"]:
            value = value.split(",")
        elif key in ["auto_schedule"]:
            value = value.lower() in ["true", "1", "yes"]
        elif key in ["posts_per_batch"]:
            value = int(value)

        pm.update_project(project.project_id, **{key: value})
        print(f"✅ Updated {key}")
        return 0

    # Show config
    print(f"\n⚙️  Project: {project.name}")
    print("=" * 60)

    config = project.config

    print(f"\n📱 Platforms: {', '.join(config.platforms)}")
    print(f"   Default: {config.default_platform}")

    print("\n📝 Content")
    print(f"   Pillars: {', '.join(config.pillars)}")
    print(f"   Tone: {config.tone}")
    print(f"   Posts per batch: {config.posts_per_batch}")

    print("\n📅 Typefully Social Sets")
    print("   (Which accounts to post to - find IDs in Typefully with Dev mode)")
    twitter_set = config.twitter_social_set_id or "❌ Not set"
    linkedin_set = config.linkedin_social_set_id or "❌ Not set"
    print(f"   Twitter:  {twitter_set}")
    print(f"   LinkedIn: {linkedin_set}")

    print("\n⏰ Scheduling")
    print(f"   Auto-schedule: {config.auto_schedule}")
    print(f"   Times: {', '.join(config.schedule_times)}")

    print("\n" + "=" * 60)
    return 0


def cmd_project_delete(args):
    """Delete a project"""
    pm = get_project_manager()

    project = pm.get_project_by_name(args.name) or pm.get_project(args.name)
    if not project:
        print(f"❌ Project not found: {args.name}")
        return 1

    if not args.confirm:
        print(f"⚠️  This will delete project '{project.name}' and all its data.")
        print("   Run with --confirm to proceed.")
        return 1

    pm.delete_project(project.project_id, confirm=True)
    print(f"✅ Deleted project: {project.name}")
    return 0


# =============================================================================
# Content Commands
# =============================================================================

def cmd_generate(args):
    """Generate new content for current project"""
    pm = get_project_manager()
    project = pm.get_current_project()

    if not project:
        print("❌ No project selected")
        print("   Use 'draper project switch <name>' first")
        return 1

    from feedback import FeedbackManager
    from generator.llm_content_generator import LLMContentGenerator

    print(f"📁 Project: {project.name}")
    print(f"🤖 Generating {args.count} posts for {args.platform}...")

    try:
        generator = LLMContentGenerator()

        # Use project-specific data directory
        project_data_dir = pm.get_project_data_dir(project.project_id)
        project_data_dir.mkdir(parents=True, exist_ok=True)
        feedback = FeedbackManager(data_dir=str(project_data_dir))

        platforms = ["twitter", "linkedin"] if args.platform == "both" else [args.platform]

        # Filter platforms to only those enabled for this project
        platforms = [p for p in platforms if p in project.config.platforms]

        if not platforms:
            print("❌ No enabled platforms match your selection")
            print(f"   Project platforms: {', '.join(project.config.platforms)}")
            return 1

        result = generator.generate_batch(
            count=args.count,
            platforms=platforms,
            pillars=project.config.pillars
        )

        posts = result.get("posts", [])

        for post in posts:
            # TAG CONTENT WITH PROJECT ID - Critical for safety
            post["project_id"] = project.project_id
            post["project_name"] = project.name
            feedback.add_for_review(post, channel="CLI")

        print(f"✅ Generated {len(posts)} posts for {project.name}")
        print("   Run 'draper review' to review and schedule them")

        return 0

    except Exception as e:
        print(f"❌ Generation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_status(args):
    """Show pipeline status for current project"""
    pm = get_project_manager()
    project = pm.get_current_project()

    if not project:
        # Show all projects summary
        projects = pm.list_projects()
        if not projects:
            print("\n⚠️  No projects configured")
            print("   Create one with: draper project add <name>")
            return 0

        print("\n📊 All Projects Status")
        print("=" * 50)

        for p in projects:
            project_data_dir = pm.get_project_data_dir(p.project_id)
            from feedback import FeedbackManager
            feedback = FeedbackManager(data_dir=str(project_data_dir))
            stats = feedback.get_stats()

            print(f"\n📁 {p.name}")
            print(f"   Pending: {stats['pending']}  Approved: {stats['approved']}  Scheduled: {stats['scheduled']}")

        print("\n" + "=" * 50)
        return 0

    # Show current project status
    project_data_dir = pm.get_project_data_dir(project.project_id)
    from feedback import FeedbackManager
    feedback = FeedbackManager(data_dir=str(project_data_dir))

    pending = feedback.get_pending_reviews()
    approved = feedback.get_approved()
    stats = feedback.get_stats()

    print("\n" + "=" * 50)
    print(f"📊 {project.name.upper()}")
    print("=" * 50)

    typefully = "✅" if project.has_typefully_configured() else "❌ Not configured"
    print(f"\n🔧 Typefully: {typefully}")

    # Count by platform
    by_platform = stats.get("by_platform", {})

    print(f"\n📝 Pending Review: {stats['pending']}")
    for platform, counts in by_platform.items():
        if counts["pending"] > 0:
            print(f"   {platform.title()}: {counts['pending']}")

    print(f"\n✅ Approved: {stats['approved']}")
    print(f"📅 Scheduled: {stats['scheduled']}")

    if pending:
        print("\n📋 Recent pending:")
        for p in pending[:5]:
            platform = p["post_data"].get("platform", "?")
            topic = p["post_data"].get("topic", "Untitled")[:40]
            print(f"   • [{platform}] {topic}")

    print("\n" + "=" * 50 + "\n")
    return 0


def cmd_review(args):
    """Review pending content"""
    pm = get_project_manager()
    project = pm.get_current_project()

    if not project:
        print("❌ No project selected")
        print("   Use 'draper project switch <name>' first")
        return 1

    if args.web:
        # Start web dashboard
        print(f"📁 Project: {project.name}")
        print(f"🚀 Starting dashboard on http://localhost:{args.port}")

        import os
        import subprocess

        # Set project context for dashboard
        env = os.environ.copy()
        env["DRAPER_PROJECT_ID"] = project.project_id

        subprocess.run([
            sys.executable,
            "-m", "dashboard.unified_dashboard",
            "--run-server",
            "--port", str(args.port)
        ], env=env)
    else:
        # CLI review
        project_data_dir = pm.get_project_data_dir(project.project_id)
        from feedback import FeedbackManager
        from data.review_models import ReviewAction
        from services.project_context import ProjectContextService
        from services.publishing_service import ProjectPublishingService
        from services.review_workflow_service import (
            ReviewTransitionError,
            ReviewWorkflowService,
        )

        feedback = FeedbackManager(data_dir=str(project_data_dir))
        project_context = ProjectContextService(pm)
        publishing_service = ProjectPublishingService(
            pm,
            data_dir=pm.data_dir,
            project_context=project_context,
        )
        review_workflow = ReviewWorkflowService(
            feedback,
            project_context,
            publishing_service,
        )

        pending = feedback.get_pending_reviews()

        if not pending:
            print(f"✅ No content pending review for {project.name}")
            return 0

        print(f"\n📁 Project: {project.name}")
        print(f"📝 {len(pending)} items pending review\n")

        for i, item in enumerate(pending[:10], 1):
            post = item["post_data"]

            # Show project context prominently
            content_project = post.get("project_name", "unknown")
            if content_project != project.name:
                print(f"⚠️  WARNING: Content from different project: {content_project}")

            print(f"{'='*60}")
            print(f"[{i}] {post.get('platform', '?').upper()} - {post.get('pillar', '')}")
            print(f"    Topic: {post.get('topic', 'Untitled')}")
            print(f"{'='*60}")
            print(post.get("content", "")[:500])
            if len(post.get("content", "")) > 500:
                print("...")
            print()

            action = input("(a)pprove, (r)eject, (s)kip, (q)uit? ").lower().strip()

            if action == "q":
                break
            elif action == "a":
                review_id = item.get("review_id")
                try:
                    review_workflow.transition(review_id, ReviewAction.APPROVE)
                    print("✅ Approved")
                except ReviewTransitionError as e:
                    print(f"⚠️  {e.code}: {e.message}")
            elif action == "r":
                review_id = item.get("review_id")
                try:
                    review_workflow.transition(review_id, ReviewAction.DECLINE)
                    print("❌ Rejected")
                except ReviewTransitionError as e:
                    print(f"⚠️  {e.code}: {e.message}")
            elif action == "s":
                print("⏭️  Skipped")

            print()

        return 0


def cmd_schedule(args):
    """Schedule approved content to Typefully"""
    import os

    pm = get_project_manager()
    project = pm.get_current_project()

    if not project:
        print("❌ No project selected")
        print("   Use 'draper project switch <name>' first")
        return 1

    if not project.has_typefully_configured():
        print(f"❌ Typefully social sets not configured for {project.name}")
        print("   Configure with:")
        print("   draper project config --set twitter_social_set_id=YOUR_TWITTER_SET_ID")
        print("   draper project config --set linkedin_social_set_id=YOUR_LINKEDIN_SET_ID")
        print("\n   Find IDs in Typefully: Settings → API → Enable Development mode")
        return 1

    # Check global Typefully API key
    typefully_key = os.getenv("TYPEFULLY_API_KEY")
    if not typefully_key:
        print("❌ TYPEFULLY_API_KEY not set in environment")
        print("   Add to .env: TYPEFULLY_API_KEY=your_key")
        return 1

    project_data_dir = pm.get_project_data_dir(project.project_id)
    from feedback import FeedbackManager
    feedback = FeedbackManager(data_dir=str(project_data_dir))

    approved = feedback.get_approved()

    if not approved:
        print(f"✅ No approved content to schedule for {project.name}")
        return 0

    print(f"📁 Project: {project.name}")
    print(f"📅 Scheduling {len(approved)} posts to Typefully...")

    try:
        from integrations.typefully import TypefullySyncClient

        # Use GLOBAL Typefully key with PROJECT-SPECIFIC social set IDs
        with TypefullySyncClient() as client:
            scheduled_count = 0
            skipped_count = 0

            for item in approved:
                post = item["post_data"]

                # SAFETY CHECK: Verify content belongs to this project
                content_project_id = post.get("project_id")
                if content_project_id and content_project_id != project.project_id:
                    print("   ⚠️  SKIPPED: Content belongs to different project")
                    print(f"      Content project: {post.get('project_name', content_project_id)}")
                    print(f"      Current project: {project.name}")
                    skipped_count += 1
                    continue

                content = post.get("content", "")
                platform = post.get("platform", "twitter")

                # Get the social set ID for this platform and project
                social_set_id = project.get_social_set_id(platform)
                if not social_set_id:
                    print(f"   ⚠️  SKIPPED: No {platform} social set configured for {project.name}")
                    skipped_count += 1
                    continue

                result = client.create_and_schedule(
                    content=content,
                    social_set_id=social_set_id,
                    share_on_linkedin=platform == "linkedin"
                )

                print(f"   ✅ [{platform}] {post.get('topic', 'Untitled')[:40]}")

                # Mark as scheduled
                review_id = item.get("review_id")
                feedback.mark_scheduled(review_id, result)
                scheduled_count += 1

        print(f"\n✅ Scheduled {scheduled_count} posts for {project.name}")
        if skipped_count:
            print(f"⚠️  Skipped {skipped_count} posts (wrong project or missing config)")
        return 0

    except Exception as e:
        print(f"❌ Scheduling failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_migrate(args):
    """Import legacy JSON data into SQLite."""
    from data.sqlite_store import SQLiteStore

    data_dir = Path(args.data_dir) if args.data_dir else Path("data")

    if not data_dir.exists():
        print(f"Error: data directory not found: {data_dir}")
        return 1

    mode = "dry-run" if args.dry_run else "live"
    print(f"Running migration ({mode}) from {data_dir} ...")

    if args.dry_run:
        # Create a lightweight store just to call run_migration_report.
        # dry_run=True internally creates a temp-file database and discards it.
        store = SQLiteStore(data_dir=data_dir, migrate=False)
        report = store.run_migration_report(dry_run=True, data_dir=data_dir)
    else:
        store = SQLiteStore(data_dir=data_dir, migrate=False)
        report = store.run_migration_report(dry_run=False)

    print(report.summary())

    if report.has_errors:
        print(f"\n⚠  {len(report.errors)} error(s) encountered during migration.")
        return 1

    print("\n✅ Migration complete.")
    return 0


def cmd_scheduler_tick(args):
    """Enqueue generate_content jobs for projects whose schedule is due."""
    from dotenv import load_dotenv
    load_dotenv()
    from dashboard.app_container import AppContainer
    from services.scheduler_producer import SchedulerProducer

    data_dir = Path(args.data_dir) if args.data_dir else get_data_dir()
    container = AppContainer(data_dir=str(data_dir))
    dry_run = bool(getattr(args, "dry_run", False))
    producer = SchedulerProducer(container, dry_run=dry_run)
    if dry_run:
        original = container.job_queue.enqueue
        calls = []

        def _stub(*a, **kw):
            calls.append((a, kw))
            return {"job_id": "dry-run"}

        container.job_queue.enqueue = _stub
        try:
            result = producer.tick()
        finally:
            container.job_queue.enqueue = original
        print(f"Would enqueue {len(calls)} generate_content job(s) for: {result['enqueued']}")
        return 0
    result = producer.tick()
    print(f"Enqueued {len(result['enqueued'])} generate_content job(s).")
    return 0


def cmd_idea_mining_tick(args):
    """Enqueue mine_ideas jobs for projects with idea_mining.enabled."""
    from dotenv import load_dotenv
    load_dotenv()
    from dashboard.app_container import AppContainer
    from services.idea_mining_producer import IdeaMiningProducer

    data_dir = Path(args.data_dir) if args.data_dir else get_data_dir()
    container = AppContainer(data_dir=str(data_dir))
    dry_run = bool(getattr(args, "dry_run", False))
    force = getattr(args, "force_project", None) or None
    producer = IdeaMiningProducer(container, dry_run=dry_run)

    if dry_run:
        original = container.job_queue.enqueue
        calls = []

        def _stub(*a, **kw):
            calls.append((a, kw))
            return {"job_id": "dry-run"}

        container.job_queue.enqueue = _stub
        try:
            result = producer.tick(force_project_id=force)
        finally:
            container.job_queue.enqueue = original
        print(json.dumps({"dry_run": True, "would_enqueue": result["enqueued"], **result}, default=str))
        return 0

    result = producer.tick(force_project_id=force)
    print(json.dumps(result, default=str))
    return 0


def cmd_idea_mining_enable(args):
    """Enable idea_mining on a project config (idempotent)."""
    from dotenv import load_dotenv
    load_dotenv()
    from dashboard.app_container import AppContainer
    from services.idea_mining_producer import resolve_idea_mining_config

    data_dir = Path(args.data_dir) if args.data_dir else get_data_dir()
    container = AppContainer(data_dir=str(data_dir))
    target = args.project
    pm = container.project_manager
    project = pm.get_project(target)
    if project is None:
        getter = getattr(pm, "get_project_by_slug", None)
        if callable(getter):
            project = getter(target)
    if project is None:
        record = None
        store = container.store
        by_slug = getattr(store, "get_project_record_by_slug", None)
        if callable(by_slug):
            record = by_slug(target)
        if record is None:
            by_name = getattr(store, "get_project_record_by_name", None)
            if callable(by_name):
                record = by_name(target)
        if record:
            project = pm.get_project(record["project_id"])
    if project is None:
        getter = getattr(pm, "get_project_by_name", None)
        if callable(getter):
            project = getter(target)
    if not project:
        print(json.dumps({"success": False, "error": f"project not found: {target}"}))
        return 1
    pid = project.project_id
    record = container.store.get_project_record(pid) or {}
    config = dict(record.get("config") or {})
    mining = resolve_idea_mining_config(record)
    mining["enabled"] = True
    if getattr(args, "frequency", None):
        mining["frequency"] = args.frequency
    if getattr(args, "max_ideas", None) is not None:
        mining["max_ideas"] = int(args.max_ideas)
    config["idea_mining"] = mining
    container.project_manager.update_project(pid, **{"idea_mining": mining})
    # ensure nested config persisted even if update_project flattens
    record = container.store.get_project_record(pid) or {}
    cfg = dict(record.get("config") or {})
    cfg["idea_mining"] = mining
    record["config"] = cfg
    container.store.save_project_record(record)
    print(json.dumps({"success": True, "project_id": pid, "idea_mining": mining}))
    return 0


def cmd_jobs_recover(args):
    """Mark stuck (long-running) jobs as failed so they can be re-enqueued."""
    from dotenv import load_dotenv
    load_dotenv()
    from dashboard.app_container import AppContainer

    data_dir = Path(args.data_dir) if args.data_dir else get_data_dir()
    container = AppContainer(data_dir=str(data_dir))
    threshold = int(args.threshold_minutes)
    if threshold < 1 or threshold > 1440:
        print(f"Error: threshold_minutes must be between 1 and 1440 (got {threshold})")
        return 1
    recovered = container.job_queue.recover_stuck(threshold_minutes=threshold)
    print(f"Recovered {len(recovered)} stuck job(s) (threshold: {threshold} min).")
    for job in recovered:
        print(
            f"  - {job.get('job_id')} [{job.get('kind')}] "
            f"started_at={job.get('started_at')}"
        )
    return 0


def cmd_config(args):
    """Show global configuration"""
    import os

    from dotenv import load_dotenv

    env_file = Path(__file__).parent / ".env"

    if env_file.exists():
        load_dotenv(env_file)

    print("\n⚙️  Global Configuration")
    print("=" * 50)

    configs = [
        ("ANTHROPIC_API_KEY", "LLM API (Claude)", True),
        ("OPENAI_API_KEY", "LLM API (OpenAI)", True),
        ("ANTHROPIC_BASE_URL", "API endpoint", False),
        ("LLM_MODEL", "Model name", False),
    ]

    for key, desc, sensitive in configs:
        value = os.getenv(key, "")
        if value:
            display = f"{value[:8]}..." if sensitive and len(value) > 8 else value
            print(f"✅ {key}: {display}")
        else:
            print(f"❌ {key}: not set ({desc})")

    print("\n" + "=" * 50)
    print(f"Config file: {env_file}")
    print()

    # Show current project
    show_current_project()
    print()

    return 0


# =============================================================================
# Idea Lab CLI helpers
# =============================================================================

def _get_idea_lab():
    """Construct an IdeaLabService from the project manager's store."""
    from data.sqlite_store import SQLiteStore
    from services.idea_lab import IdeaLabService

    data_dir = str(get_data_dir())
    store = SQLiteStore(data_dir=data_dir, migrate=True)
    return IdeaLabService(store)


def _idea_to_json(idea_or_dict) -> str:
    """Serialize a ContentIdea or dict to pretty JSON."""

    if hasattr(idea_or_dict, "to_dict"):
        data = idea_or_dict.to_dict()
    else:
        data = idea_or_dict
    return json.dumps(data, indent=2, default=str)


def cmd_ideas_material_add(args):
    """Add source material via CLI."""
    try:
        service = _get_idea_lab()
        result = service.add_source_material(
            project_id=args.project_id or "",
            url=args.url,
            text_content=args.text,
            note=args.note,
            title=args.title,
            tags=args.tags.split(",") if args.tags else None,
        )
        print(_idea_to_json(result))
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    return 0


def cmd_ideas_material_list(args):
    """List source materials via CLI."""
    service = _get_idea_lab()
    project_id = args.project_id or ""
    materials = service.list_source_material(
        project_id=project_id,
        material_type=args.type,
        limit=int(args.limit) if args.limit else None,
    )
    if not materials:
        print("No source materials found.")
        return 0
    # Table output
    print(f"{'ID':<20} {'Type':<8} {'Title':<40}")
    print("-" * 68)
    for m in materials:
        d = m.to_dict() if hasattr(m, "to_dict") else m
        print(f"{d.get('material_id', ''):<20} {d.get('material_type', ''):<8} {(d.get('title') or '')[:40]:<40}")
    print(f"\nTotal: {len(materials)}")
    return 0


def cmd_ideas_material_get(args):
    """Get a single source material via CLI."""
    service = _get_idea_lab()
    material = service.get_source_material(args.material_id)
    if material is None:
        print(f"Source material '{args.material_id}' not found.")
        return 1
    print(_idea_to_json(material))
    return 0


def cmd_ideas_material_delete(args):
    """Delete a source material via CLI."""
    service = _get_idea_lab()
    deleted = service.delete_source_material(args.material_id)
    if deleted:
        print(f"Deleted source material '{args.material_id}'.")
    else:
        print(f"Source material '{args.material_id}' not found.")
        return 1
    return 0


def cmd_ideas_idea_add(args):
    """Add a content idea via CLI."""
    try:
        service = _get_idea_lab()
        result = service.add_content_idea(
            project_id=args.project_id or "",
            title=args.title,
            hook_angle=args.hook or "",
            target_platforms=args.platforms.split(",") if args.platforms else None,
            content_pillar=args.pillar or "",
            tags=args.tags.split(",") if args.tags else None,
        )
        print(_idea_to_json(result))
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    return 0


def cmd_ideas_idea_list(args):
    """List content ideas via CLI."""
    service = _get_idea_lab()
    ideas = service.list_content_ideas(
        project_id=args.project_id or "",
        status=args.status,
        content_pillar=args.pillar,
        limit=int(args.limit) if args.limit else None,
    )
    if not ideas:
        print("No content ideas found.")
        return 0
    # Table output
    print(f"{'ID':<20} {'Status':<10} {'Pillar':<15} {'Title':<40}")
    print("-" * 85)
    for idea in ideas:
        d = idea.to_dict() if hasattr(idea, "to_dict") else idea
        print(f"{d.get('idea_id', ''):<20} {d.get('status', ''):<10} {d.get('content_pillar', ''):<15} {(d.get('title') or '')[:40]:<40}")
    print(f"\nTotal: {len(ideas)}")
    return 0


def cmd_ideas_idea_get(args):
    """Get a single content idea via CLI."""
    service = _get_idea_lab()
    idea = service.get_content_idea(args.idea_id)
    if idea is None:
        print(f"Content idea '{args.idea_id}' not found.")
        return 1
    print(_idea_to_json(idea))
    return 0


def cmd_ideas_idea_update(args):
    """Update a content idea via CLI."""
    try:
        service = _get_idea_lab()
        kwargs = {}
        if args.title:
            kwargs["title"] = args.title
        if args.hook:
            kwargs["hook_angle"] = args.hook
        if args.tags:
            kwargs["tags"] = args.tags.split(",")
        if not kwargs:
            print("No fields to update. Use --title, --hook, or --tags.")
            return 1
        result = service.update_content_idea(args.idea_id, **kwargs)
        print(_idea_to_json(result))
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    return 0


def cmd_ideas_idea_evaluate(args):
    """Evaluate (change status of) a content idea via CLI."""
    try:
        service = _get_idea_lab()
        result = service.evaluate_content_idea(
            idea_id=args.idea_id,
            new_status=args.status,
            evaluation_notes=args.notes,
        )
        print(_idea_to_json(result))
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    return 0


def cmd_ideas_idea_delete(args):
    """Delete a content idea via CLI."""
    service = _get_idea_lab()
    deleted = service.delete_content_idea(args.idea_id)
    if deleted:
        print(f"Deleted content idea '{args.idea_id}'.")
    else:
        print(f"Content idea '{args.idea_id}' not found.")
        return 1
    return 0


def cmd_ideas_mine(args):
    """Enqueue mine_ideas for a project (uses idea-mining producer with --force)."""
    class _Args:
        data_dir = getattr(args, "data_dir", None)
        dry_run = False
        force_project = getattr(args, "project_id", None)
    if not _Args.force_project:
        print("Error: --project-id is required")
        return 1
    return cmd_idea_mining_tick(_Args())


def main():
    parser = argparse.ArgumentParser(
        prog="draper",
        description="AI-powered marketing content pipeline with multi-project support"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Project commands
    project_parser = subparsers.add_parser("project", help="Manage projects")
    project_sub = project_parser.add_subparsers(dest="project_command")

    # project list
    project_list = project_sub.add_parser("list", help="List all projects")
    project_list.set_defaults(func=cmd_project_list)

    # project add
    project_add = project_sub.add_parser("add", help="Add a new project")
    project_add.add_argument("name", help="Project name")
    project_add.add_argument("-d", "--description", help="Project description")
    project_add.add_argument("-t", "--typefully-key", help="Typefully API key")
    project_add.add_argument("-p", "--platforms", default="twitter,linkedin",
                            help="Platforms (comma-separated)")
    project_add.set_defaults(func=cmd_project_add)

    # project switch
    project_switch = project_sub.add_parser("switch", help="Switch to a project")
    project_switch.add_argument("name", help="Project name or ID")
    project_switch.set_defaults(func=cmd_project_switch)

    # project config
    project_config = project_sub.add_parser("config", help="Show/update project config")
    project_config.add_argument("--set", help="Set config value (KEY=VALUE)")
    project_config.set_defaults(func=cmd_project_config)

    # project delete
    project_delete = project_sub.add_parser("delete", help="Delete a project")
    project_delete.add_argument("name", help="Project name or ID")
    project_delete.add_argument("--confirm", action="store_true", help="Confirm deletion")
    project_delete.set_defaults(func=cmd_project_delete)

    # generate
    gen_parser = subparsers.add_parser("generate", help="Generate content for current project")
    gen_parser.add_argument("-n", "--count", type=int, default=5, help="Number of posts")
    gen_parser.add_argument("-p", "--platform", choices=["twitter", "linkedin", "both"],
                           default="both", help="Target platform")
    gen_parser.set_defaults(func=cmd_generate)

    # status
    status_parser = subparsers.add_parser("status", help="Show pipeline status")
    status_parser.set_defaults(func=cmd_status)

    # review
    review_parser = subparsers.add_parser("review", help="Review pending content")
    review_parser.add_argument("--web", action="store_true", help="Start web dashboard")
    review_parser.add_argument("--port", type=int, default=8765, help="Dashboard port")
    review_parser.set_defaults(func=cmd_review)

    # schedule
    schedule_parser = subparsers.add_parser("schedule", help="Schedule approved content")
    schedule_parser.set_defaults(func=cmd_schedule)

    # scheduler (producer)
    scheduler_parser = subparsers.add_parser("scheduler", help="Generation scheduler commands")
    scheduler_sub = scheduler_parser.add_subparsers(dest="scheduler_command")
    scheduler_tick_cmd = scheduler_sub.add_parser(
        "tick", help="Enqueue generate_content jobs for due projects"
    )
    scheduler_tick_cmd.add_argument("--data-dir", help="Data directory")
    scheduler_tick_cmd.add_argument(
        "--dry-run", action="store_true", help="Print what would be enqueued"
    )
    scheduler_tick_cmd.set_defaults(func=cmd_scheduler_tick)


    # idea-mining (autonomic Idea Lab)
    idea_mining_parser = subparsers.add_parser(
        "idea-mining", help="Idea Lab mining producer commands"
    )
    idea_mining_sub = idea_mining_parser.add_subparsers(dest="idea_mining_command")
    idea_mining_tick = idea_mining_sub.add_parser(
        "tick", help="Enqueue mine_ideas jobs for due enabled projects"
    )
    idea_mining_tick.add_argument("--data-dir", help="Data directory")
    idea_mining_tick.add_argument(
        "--dry-run", action="store_true", help="Print what would be enqueued"
    )
    idea_mining_tick.add_argument(
        "--force-project",
        help="Force a single project_id (bypasses enabled/due checks for that project)",
    )
    idea_mining_tick.set_defaults(func=cmd_idea_mining_tick)
    idea_mining_enable = idea_mining_sub.add_parser(
        "enable", help="Enable idea_mining on a project (idempotent)"
    )
    idea_mining_enable.add_argument("project", help="Project id, slug, or name")
    idea_mining_enable.add_argument(
        "--frequency",
        choices=["daily", "weekdays", "weekly"],
        default="weekdays",
    )
    idea_mining_enable.add_argument("--max-ideas", type=int, default=5)
    idea_mining_enable.add_argument("--data-dir", help="Data directory")
    idea_mining_enable.set_defaults(func=cmd_idea_mining_enable)

    # jobs (recovery)
    jobs_parser = subparsers.add_parser("jobs", help="Job queue commands")
    jobs_sub = jobs_parser.add_subparsers(dest="jobs_command")
    jobs_recover = jobs_sub.add_parser("recover", help="Recover stuck jobs")
    jobs_recover.add_argument(
        "--stuck", action="store_true", help="Mark long-running jobs as failed"
    )
    jobs_recover.add_argument(
        "--threshold-minutes", type=int, default=30, help="Stuck threshold (default 30)"
    )
    jobs_recover.add_argument("--data-dir", help="Data directory")
    jobs_recover.set_defaults(func=cmd_jobs_recover)

    # migrate
    migrate_parser = subparsers.add_parser(
        "migrate", help="Import legacy JSON data into SQLite"
    )
    migrate_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Preview import without writing to the database",
    )
    migrate_parser.add_argument(
        "--data-dir", type=str, default=None,
        help="Path to data directory (default: data/)",
    )
    migrate_parser.set_defaults(func=cmd_migrate)

    # config
    config_parser = subparsers.add_parser("config", help="Show global configuration")
    config_parser.set_defaults(func=cmd_config)

    # ---- ideas subparser ----
    ideas_parser = subparsers.add_parser("ideas", help="Idea Lab: manage source materials and content ideas")
    ideas_sub = ideas_parser.add_subparsers(dest="ideas_command")

    # -- ideas material --
    ideas_material = ideas_sub.add_parser("material", help="Manage source materials")
    ideas_material_sub = ideas_material.add_subparsers(dest="material_command")

    mat_add = ideas_material_sub.add_parser("add", help="Add source material")
    mat_add.add_argument("--project-id", help="Project ID (defaults to current)")
    mat_add.add_argument("--url", help="Source URL")
    mat_add.add_argument("--text", help="Text content")
    mat_add.add_argument("--note", help="Note")
    mat_add.add_argument("--title", help="Title")
    mat_add.add_argument("--tags", help="Comma-separated tags")
    mat_add.set_defaults(func=cmd_ideas_material_add)

    mat_list = ideas_material_sub.add_parser("list", help="List source materials")
    mat_list.add_argument("--project-id", help="Project ID")
    mat_list.add_argument("--type", help="Filter by material type (url/text/note)")
    mat_list.add_argument("--limit", help="Max results")
    mat_list.set_defaults(func=cmd_ideas_material_list)

    mat_get = ideas_material_sub.add_parser("get", help="Get a source material")
    mat_get.add_argument("material_id", help="Material ID")
    mat_get.set_defaults(func=cmd_ideas_material_get)

    mat_del = ideas_material_sub.add_parser("delete", help="Delete a source material")
    mat_del.add_argument("material_id", help="Material ID")
    mat_del.set_defaults(func=cmd_ideas_material_delete)

    # -- ideas idea --
    ideas_idea = ideas_sub.add_parser("idea", help="Manage content ideas")
    ideas_idea_sub = ideas_idea.add_subparsers(dest="idea_command")

    idea_add = ideas_idea_sub.add_parser("add", help="Add a content idea")
    idea_add.add_argument("--project-id", help="Project ID")
    idea_add.add_argument("--title", required=True, help="Idea title")
    idea_add.add_argument("--hook", help="Hook angle")
    idea_add.add_argument("--platforms", help="Comma-separated target platforms")
    idea_add.add_argument("--pillar", help="Content pillar")
    idea_add.add_argument("--tags", help="Comma-separated tags")
    idea_add.set_defaults(func=cmd_ideas_idea_add)

    idea_list = ideas_idea_sub.add_parser("list", help="List content ideas")
    idea_list.add_argument("--project-id", help="Project ID")
    idea_list.add_argument("--status", help="Filter by status (draft/approved/rejected)")
    idea_list.add_argument("--pillar", help="Filter by content pillar")
    idea_list.add_argument("--limit", help="Max results")
    idea_list.set_defaults(func=cmd_ideas_idea_list)

    idea_get = ideas_idea_sub.add_parser("get", help="Get a content idea")
    idea_get.add_argument("idea_id", help="Idea ID")
    idea_get.set_defaults(func=cmd_ideas_idea_get)

    idea_update = ideas_idea_sub.add_parser("update", help="Update a content idea")
    idea_update.add_argument("idea_id", help="Idea ID")
    idea_update.add_argument("--title", help="New title")
    idea_update.add_argument("--hook", help="New hook angle")
    idea_update.add_argument("--tags", help="New comma-separated tags")
    idea_update.set_defaults(func=cmd_ideas_idea_update)

    idea_eval = ideas_idea_sub.add_parser("evaluate", help="Evaluate a content idea")
    idea_eval.add_argument("idea_id", help="Idea ID")
    idea_eval.add_argument("--status", required=True, help="New status (draft/approved/rejected)")
    idea_eval.add_argument("--notes", help="Evaluation notes")
    idea_eval.set_defaults(func=cmd_ideas_idea_evaluate)

    idea_del = ideas_idea_sub.add_parser("delete", help="Delete a content idea")
    idea_del.add_argument("idea_id", help="Idea ID")
    idea_del.set_defaults(func=cmd_ideas_idea_delete)

    # -- ideas mine --
    ideas_mine = ideas_sub.add_parser("mine", help="Trigger idea mining (placeholder)")
    ideas_mine.add_argument("--project-id", help="Project ID")
    ideas_mine.set_defaults(func=cmd_ideas_mine)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "project" and not hasattr(args, "func"):
        project_parser.print_help()
        return 0

    if args.command == "ideas" and not hasattr(args, "func"):
        ideas_parser.print_help()
        return 0

    if args.command == "scheduler" and not hasattr(args, "func"):
        scheduler_parser.print_help()
    if args.command == "idea-mining" and not hasattr(args, "func"):
        idea_mining_parser.print_help()
        return 0
        return 0
        return 0

    if args.command == "jobs" and not hasattr(args, "func"):
        jobs_parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
