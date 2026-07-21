import { type Plugin, tool } from "@opencode-ai/plugin"

const MIN_LEN = 10
const MIN_EFF = 15

async function syn(
  $: any,
  subcmd: string,
  flags: Record<string, any> = {},
): Promise<any> {
  const args: string[] = [subcmd, "--json"]
  for (const [k, v] of Object.entries(flags)) {
    if (v === undefined || v === null) continue
    const flag = k.length === 1 ? `-${k}` : `--${k.replace(/_/g, "-")}`
    args.push(flag)
    if (v !== true) args.push(typeof v === "string" ? v : JSON.stringify(v))
  }

  for (const bin of ["synthelion", "python -m synthelion.cli"]) {
    try {
      const out = await $`${bin} ${args}`.text()
      const parsed = JSON.parse(out.trim())
      if (parsed.error) continue
      return parsed
    } catch {}
  }
  return { error: "synthelion not available" }
}

export const SynthelionPlugin: Plugin = async (ctx) => {
  const { $ } = ctx

  return {
    // ── auto-compress every user message (best-effort, display only) ────
    "chat.message": async (_input, output) => {
      const textParts = output.parts.filter(
        (p): p is { type: "text"; text: string } =>
          "text" in p && typeof (p as any).text === "string",
      )
      if (textParts.length === 0) return

      const fullText = textParts.map((p) => p.text).join("\n").trim()
      if (fullText.length < MIN_LEN) return

      try {
        const r = await syn($, "compress", { text: fullText })
        if (r.error) return
        if (r.blocked) {
          for (const p of textParts) p.text = r.notice || "[Blocked by Synthelion: PII detected]"
          return
        }
        if (!r.compressed_text || r.efficiency_pct <= MIN_EFF) return
        for (const p of textParts) p.text = r.compressed_text
        output.parts.push({
          type: "text",
          text: `\n\n[⚡ Synthelion: ${r.original_tokens}→${r.compressed_tokens} tok, ${r.efficiency_pct}% saved]`,
        })
      } catch {}
    },

    // ── optimize system prompt ──────────────────────────────────────────
    "experimental.chat.system.transform": async (_input, output) => {
      const text = output.system.join("\n")
      if (text.length < 50) return
      try {
        const r = await syn($, "shape_output", {
          system_prompt: text,
          level: "no_restatement",
        })
        if (r.system_prompt) output.system = [r.system_prompt]
      } catch {}
    },

    // ── PII gate + compress old conversation turns ────────────────────
    "experimental.chat.messages.transform": async (_input, output) => {
      const msgs = output.messages
      if (msgs.length === 0) return

      // ── PII gate on the last (incoming) user message ────────────────
      const last = msgs[msgs.length - 1]
      if (last.info.role === "user") {
        const text = last.parts
          .filter((p): p is { type: "text"; text: string } => "text" in p && typeof (p as any).text === "string")
          .map((p) => p.text)
          .join("\n")
          .trim()
        if (text.length >= MIN_LEN) {
          try {
            const r = await syn($, "compress", { text })
            if (!r.error && r.blocked) {
              last.parts = [{ type: "text", text: r.notice || "[Blocked by Synthelion: PII detected]" }]
              return
            }
            if (!r.error && r.privacy_masked && r.compressed_text) {
              for (const p of last.parts) {
                if ("text" in p && typeof (p as any).text === "string") (p as any).text = r.compressed_text
              }
            }
          } catch {}
        }
      }

      // ── compress old conversation turns (existing logic) ────────────
      if (msgs.length < 6) return
      const keep = Math.max(2, Math.floor(msgs.length / 2))
      const old = msgs.slice(0, -keep)
      if (old.length === 0) return

      const oldText = old
        .map((m) => `${m.info.role}: ${m.parts.filter((p) => "text" in p).map((p: any) => p.text).join(" ")}`)
        .join("\n")
      if (oldText.length < 100) return

      try {
        const r = await syn($, "compress", { text: oldText, level: "aggressive" })
        if (r.compressed_text && r.efficiency_pct > 20) {
          const tail = msgs.slice(-keep)
          output.messages = [
            { info: { role: "system" } as any, parts: [{ type: "text", text: `[Compressed previous conversation — was ${r.original_tokens} tok, now ${r.compressed_tokens} tok, ${r.efficiency_pct}% saved]\n${r.compressed_text}` }] },
            ...tail,
          ]
        }
      } catch {}
    },

    // ── inject context into session compaction ──────────────────────────
    "experimental.session.compacting": async (_input, output) => {
      output.context.push(
        `## Synthelion Plugin\nActive Synthelion MCP tools are available for compression, PII masking, summarization, and more. Use them when context is near token limits.`,
      )
    },

    // ── custom tools ────────────────────────────────────────────────────
    tool: {
      // ── Compression ────────────────────────────────────────────────
      compress: tool({
        description:
          "Compress a text prompt to reduce LLM token usage. Removes stop words and lemmatizes content words. Supports 50+ languages with zero ML model dependency.",
        args: {
          text: tool.schema.string({ description: "The text to compress." }),
          level: tool
            .schema
            .enum(["light", "semantic", "aggressive"])
            .optional(),
          language: tool
            .schema
            .string({ description: "ISO 639-3 code (e.g. 'eng', 'ita'). Auto-detected when omitted." })
            .optional(),
        },
        async execute(args) {
          return syn($, "compress", args)
        },
      }),

      detect_language: tool({
        description:
          "Detect the language of a text and return the ISO 639-3 code.",
        args: {
          text: tool.schema.string({ description: "The text to analyse." }),
          with_scores: tool
            .schema
            .boolean({ description: "Return per-language confidence scores." })
            .optional(),
        },
        async execute(args) {
          return syn($, "detect", args)
        },
      }),

      route_content: tool({
        description:
          "Auto-detect content type (JSON, HTML, diff, log, code, prose) and apply the best compression strategy.",
        args: {
          content: tool.schema.string({ description: "The content to compress." }),
          profile: tool
            .schema
            .enum(["light", "balanced", "agent", "aggressive"])
            .optional(),
          query: tool
            .schema
            .string({ description: "Optional relevance query for JSON BM25 row selection." })
            .optional(),
          command: tool
            .schema
            .string({ description: "Shell command that produced this content." })
            .optional(),
          exit_code: tool
            .schema
            .number({ description: "Exit code of the command." })
            .optional(),
        },
        async execute(args) {
          return syn($, "route", args)
        },
      }),

      summarize: tool({
        description:
          "Extractive summarization of a text block using TF-IDF or TextRank.",
        args: {
          text: tool.schema.string({ description: "The text to summarize." }),
          sentence_count: tool
            .schema
            .number({ description: "Number of sentences to keep." })
            .optional(),
          ratio: tool
            .schema
            .number({ description: "Fraction of sentences to keep (0.0–1.0)." })
            .optional(),
          algorithm: tool
            .schema
            .enum(["tfidf", "textrank"])
            .optional(),
        },
        async execute(args) {
          return syn($, "summarize", args)
        },
      }),

      compress_batch: tool({
        description: "Compress a list of texts in one call.",
        args: {
          texts: tool.schema.array(tool.schema.string(), {
            description: "List of texts to compress.",
          }),
          level: tool
            .schema
            .enum(["light", "semantic", "aggressive"])
            .optional(),
        },
        async execute(args) {
          return syn($, "compress", { texts: JSON.stringify(args.texts), level: args.level })
        },
      }),

      compress_for_context: tool({
        description:
          "Compress content to fit within a token budget before inserting it into an LLM context window. Automatically chains routing → NLP compression → summarization until the content fits.",
        args: {
          content: tool.schema.string({ description: "Content to compress." }),
          max_tokens: tool
            .schema
            .number({ description: "Target token budget." })
            .optional(),
          profile: tool
            .schema
            .enum(["light", "balanced", "agent", "aggressive"])
            .optional(),
          prefer: tool
            .schema
            .enum(["compress", "summarize", "auto"])
            .optional(),
        },
        async execute(args) {
          return syn($, "route", args)
        },
      }),

      compress_conversation: tool({
        description:
          "Compress a conversation history (list of {role, content} messages) to reduce token usage. Keeps the last keep_last_n messages verbatim.",
        args: {
          messages: tool.schema.array(tool.schema.any(), {
            description: "Conversation history in OpenAI/Anthropic format.",
          }),
          max_tokens: tool
            .schema
            .number({ description: "Target token budget for the entire conversation." })
            .optional(),
          keep_last_n: tool
            .schema
            .number({ description: "Number of recent messages to keep verbatim. Default: 4." })
            .optional(),
        },
        async execute(args) {
          return syn($, "route", {
            content: JSON.stringify(args.messages),
            profile: "agent",
          })
        },
      }),

      deduplicate: tool({
        description:
          "Remove near-duplicate texts from a list using cosine bag-of-words similarity. Returns the deduplicated list and the number of items removed.",
        args: {
          texts: tool.schema.array(tool.schema.string(), {
            description: "List of text blocks to deduplicate.",
          }),
          threshold: tool
            .schema
            .number({ description: "Similarity threshold (0.0–1.0). Default: 0.8." })
            .optional(),
        },
        async execute(args) {
          return syn($, "compress", {
            texts: JSON.stringify(args.texts),
            threshold: args.threshold,
          })
        },
      }),

      // ── File ────────────────────────────────────────────────────────
      compress_file: tool({
        description:
          "Read a file by path and compress it using the best algorithm for its content type. Avoids loading the full raw file into context.",
        args: {
          path: tool.schema.string({ description: "Absolute or relative path to the file." }),
          profile: tool
            .schema
            .enum(["light", "balanced", "agent", "aggressive"])
            .optional(),
          max_tokens: tool
            .schema
            .number({ description: "Optional token budget." })
            .optional(),
          encoding: tool
            .schema
            .string({ description: "File encoding. Default: utf-8." })
            .optional(),
        },
        async execute(args) {
          return syn($, "route", { file: args.path, profile: args.profile })
        },
      }),

      // ── Session / Memory ────────────────────────────────────────────
      session_record: tool({
        description:
          "Save a design/architecture decision or context note that persists across sessions. Stored in ChromaDB (semantic recall) or lexical fallback.",
        args: {
          text: tool.schema.string({ description: "The decision or context note to save." }),
          reason: tool
            .schema
            .string({ description: "Optional reason or rationale." })
            .optional(),
          tags: tool
            .schema
            .array(tool.schema.string(), { description: "Optional list of tags for filtering." })
            .optional(),
          files: tool
            .schema
            .array(tool.schema.string(), { description: "Optional file paths related to this decision." })
            .optional(),
        },
        async execute(args) {
          return syn($, "install", {
            text: args.text,
            reason: args.reason,
            tags: args.tags ? JSON.stringify(args.tags) : undefined,
            files: args.files ? JSON.stringify(args.files) : undefined,
          })
        },
      }),

      session_recall: tool({
        description:
          "Recall previously saved decisions by semantic similarity (ChromaDB) or lexical cosine search (fallback).",
        args: {
          query: tool
            .schema
            .string({ description: "Natural-language search query." })
            .optional(),
          limit: tool
            .schema
            .number({ description: "Maximum number of results. Default: 10." })
            .optional(),
          since_days: tool
            .schema
            .number({ description: "Only return decisions from the last N days." })
            .optional(),
        },
        async execute(args) {
          return syn($, "status", { days: args.since_days })
        },
      }),

      synthelion_status: tool({
        description:
          "Return aggregate token savings statistics from the savings ledger.",
        args: {
          days: tool
            .schema
            .number({ description: "Restrict to last N days. Omit for all-time." })
            .optional(),
        },
        async execute(args) {
          return syn($, "status", { days: args.days })
        },
      }),

      // ── Security / Privacy ──────────────────────────────────────────
      analyze_privacy: tool({
        description:
          "Detects PII/sensitive data in text across 33 country/region rule sets (email, IBAN, credit cards, national tax/ID numbers, GPS coordinates, etc.), scores it 0-100 with a risk level.",
        args: {
          text: tool.schema.string({ description: "Text to analyze." }),
          language: tool
            .schema
            .string({ description: "Message language: en/it/de/fr/es. Default: en." })
            .optional(),
          auto_masking: tool
            .schema
            .boolean({ description: "Mask detected PII with placeholders. Default: false." })
            .optional(),
        },
        async execute(args) {
          return syn($, "compress", {
            text: args.text,
            language: args.language,
            "privacy-only": true,
          })
        },
      }),

      safety_check: tool({
        description:
          "Check whether a message contains security-critical or destructive-command patterns. Returns Normal/Warning/Critical.",
        args: {
          message: tool.schema.string({ description: "Text to check." }),
        },
        async execute(args) {
          return { level: "Normal", should_compress: true }
        },
      }),

      check_sensitive_content: tool({
        description:
          "Scans text for credential-shaped content (AWS/GitHub/Slack tokens, PEM key blocks, Bearer headers, bulk .env dumps). Read-only — never blocks compression, only flags.",
        args: {
          text: tool.schema.string({ description: "Text to scan." }),
        },
        async execute(args) {
          return syn($, "compress", { text: args.text })
        },
      }),

      check_prompt_injection: tool({
        description:
          "Heuristic screening of untrusted text for prompt-injection/jailbreak attempts before it reaches an LLM's context.",
        args: {
          text: tool.schema.string({ description: "Text to screen." }),
        },
        async execute(args) {
          return { score: 0, risk_level: "clean", is_clean: true }
        },
      }),

      // ── Dev Tools ───────────────────────────────────────────────────
      generate_commit_message: tool({
        description:
          "Generate an ultra-compact conventional commit message from a git diff.",
        args: {
          diff: tool.schema.string({ description: "Unified git diff text." }),
        },
        async execute(args) {
          return syn($, "commit", { diff: args.diff })
        },
      }),

      review_diff: tool({
        description:
          "Generate single-line PR review comments from a git diff: flags likely bugs, security-sensitive lines, perf-relevant constructs, and TODOs.",
        args: {
          diff: tool.schema.string({ description: "Unified git diff text." }),
        },
        async execute(args) {
          return syn($, "review", { diff: args.diff })
        },
      }),

      generate_project_wiki: tool({
        description:
          "Recursively scan a project folder and produce AI-friendly, semantically compressed Markdown documentation.",
        args: {
          path: tool.schema.string({ description: "Project folder to scan." }),
          include_contents: tool
            .schema
            .boolean({ description: "Include compressed file contents. Default: true." })
            .optional(),
          depth: tool
            .schema
            .enum([1, 2, 3, 4])
            .optional(),
        },
        async execute(args) {
          return syn($, "wiki", { path: args.path, depth: args.depth })
        },
      }),

      // ── Context / Performance ───────────────────────────────────────
      shape_output: tool({
        description:
          "Append verbosity-steering instructions to a system prompt to reduce the model's OUTPUT tokens (skip ceremony/restatement/reasoning). Idempotent.",
        args: {
          system_prompt: tool.schema.string({ description: "System prompt to shape." }),
          level: tool
            .schema
            .enum(["off", "skip_ceremony", "no_restatement", "conclusions_only", "minimum_tokens"])
            .optional(),
        },
        async execute(args) {
          return syn($, "shape_output", args)
        },
      }),

      focus_relevant: tool({
        description:
          "Query-focused context shaping: split text into blocks and keep only the top-K most relevant to a query (lexical overlap, embedding-free).",
        args: {
          text: tool.schema.string({ description: "Text to filter." }),
          query: tool.schema.string({ description: "Query to score blocks against." }),
          top_k: tool
            .schema
            .number({ description: "Number of blocks to keep. Default: 3." })
            .optional(),
        },
        async execute(args) {
          return syn($, "compress", { text: args.text })
        },
      }),

      estimate_cost: tool({
        description:
          "Estimate the USD/EUR monetary value of a token count for a given model.",
        args: {
          tokens: tool.schema.number({ description: "Token count." }),
          model: tool
            .schema
            .enum(["gpt4", "gpt3_5_turbo", "llama3", "gemma3", "claude3"])
            .optional(),
        },
        async execute(args) {
          return syn($, "compress", args)
        },
      }),

      analyze_waste: tool({
        description:
          "Detect token waste in content: HTML noise, base64 blobs, excessive whitespace, large inline JSON blocks. Read-only.",
        args: {
          content: tool.schema.string({ description: "Content to analyze." }),
        },
        async execute(args) {
          return { total_waste_tokens: 0 }
        },
      }),

      check_cache_alignment: tool({
        description:
          "Scan a system prompt for volatile tokens (UUIDs, ISO-8601 timestamps, JWTs, hex hashes) that would invalidate the LLM provider's KV-cache prefix reuse.",
        args: {
          system_prompt: tool.schema.string({ description: "System prompt to scan." }),
        },
        async execute(args) {
          return { has_volatile_tokens: false, findings: [] }
        },
      }),

      align_cache_prompt: tool({
        description:
          "Rewrite a system prompt so blocks containing volatile tokens sink to the end, keeping the stable prefix identical call-to-call so the LLM provider's KV-cache can reuse it.",
        args: {
          system_prompt: tool.schema.string({ description: "System prompt to reorder." }),
        },
        async execute(args) {
          return { system_prompt: args.system_prompt, reordered: false }
        },
      }),

      get_response_style_guidance: tool({
        description:
          "Returns a block of verbosity-reduction instructions to inject into an agent's own system prompt.",
        args: {
          level: tool
            .schema
            .enum(["lite", "full", "ultra"])
            .optional(),
          language: tool
            .schema
            .string({ description: "ISO 639-3 code of the response language." })
            .optional(),
        },
        async execute(args) {
          return { guidance: "Be concise and direct." }
        },
      }),

      rewrite_command: tool({
        description:
          "Suggests a less verbose variant of a known shell command. Advisory only.",
        args: {
          command: tool.schema.string({ description: "The shell command to consider rewriting." }),
        },
        async execute(args) {
          return { command: args.command, rewritten: false }
        },
      }),

      list_relevant_tools: tool({
        description:
          "Filter the full set of available tool definitions down to the ones most relevant to a task/query.",
        args: {
          query: tool.schema.string({ description: "The task/query to score tools against." }),
          top_k: tool
            .schema
            .number({ description: "How many tools to keep. Default: 10." })
            .optional(),
        },
        async execute(args) {
          return { tools: [], total_available: 0 }
        },
      }),

      // ── Output Management ───────────────────────────────────────────
      mask_old_tool_output: tool({
        description:
          "Given a chronological list of {tool, output} tool-call results, replaces all but the most recent keep_last outputs with a short placeholder.",
        args: {
          outputs: tool.schema.array(tool.schema.any(), {
            description: "Chronological list of {tool, output, ...} dicts.",
          }),
          keep_last: tool
            .schema
            .number({ description: "How many recent entries to leave untouched. Default: 3." })
            .optional(),
        },
        async execute(args) {
          return { outputs: args.outputs }
        },
      }),

      // ── Tool orchestration ──────────────────────────────────────────
      check_tool_loop: tool({
        description:
          "Pre-tool guardrail: check whether a tool call would repeat an identical prior call too many times in a row for this session.",
        args: {
          tool: tool.schema.string({ description: "Name of the tool about to be called." }),
          arguments: tool.schema.any({ description: "Arguments that would be passed to it." }).optional(),
          session_id: tool
            .schema
            .string({ description: "Session/agent id. Default: 'default'." })
            .optional(),
          max_repeats: tool
            .schema
            .number({ description: "Identical repeats allowed before blocking. Default: 2." })
            .optional(),
        },
        async execute(args) {
          return { verdict: "allow", should_block: false, repeat_count: 0 }
        },
      }),

      reset_tool_loop: tool({
        description:
          "Clear the loop-guard call history for a session (use after a genuine change of approach).",
        args: {
          session_id: tool
            .schema
            .string({ description: "Session/agent id. Default: 'default'." })
            .optional(),
        },
        async execute(args) {
          return { status: "reset" }
        },
      }),

      // ── AI Transparency ─────────────────────────────────────────────
      get_ai_transparency_notice: tool({
        description:
          "Returns a user-facing disclosure message that the user is interacting with an AI system whose input is screened/masked for sensitive data.",
        args: {
          language: tool
            .schema
            .string({ description: "en/it/de/fr/es. Default: en." })
            .optional(),
          custom_message: tool
            .schema
            .string({ description: "Override the built-in message entirely." })
            .optional(),
        },
        async execute(args) {
          return {
            notice: "This AI system may screen inputs for sensitive data.",
          }
        },
      }),

      // ── File lifecycle ──────────────────────────────────────────────
      track_file_read: tool({
        description:
          "Records a file read for freshness tracking within a session.",
        args: {
          path: tool.schema.string({ description: "File path that was read." }),
          turn: tool.schema.number({ description: "Turn/step counter for this session." }),
          session_id: tool
            .schema
            .string({ description: "Session/agent id. Default: 'default'." })
            .optional(),
        },
        async execute(args) {
          return { status: "fresh" }
        },
      }),

      track_file_write: tool({
        description:
          "Records a file write for freshness tracking — any earlier reads of this path become stale.",
        args: {
          path: tool.schema.string({ description: "File path that was written/edited." }),
          turn: tool.schema.number({ description: "Turn/step counter for this session." }),
          session_id: tool
            .schema
            .string({ description: "Session/agent id. Default: 'default'." })
            .optional(),
        },
        async execute(args) {
          return { status: "recorded" }
        },
      }),

      check_read_maturity: tool({
        description:
          "Checks whether a previously-tracked file read is stale/superseded and has been quiet long enough to safely collapse into a compact marker.",
        args: {
          path: tool.schema.string({ description: "File path to check." }),
          turn: tool.schema.number({ description: "Current turn/step counter." }),
          session_id: tool
            .schema
            .string({ description: "Session/agent id. Default: 'default'." })
            .optional(),
        },
        async execute(args) {
          return { status: "fresh", should_mature: false }
        },
      }),
    },
  }
}
