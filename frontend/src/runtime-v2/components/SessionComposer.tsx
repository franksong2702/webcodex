import { useFlowingSelection } from "../../ui/useFlowingSelection.js";
import { ArrowUpRight, Check, LoaderCircle, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { clearDraft, loadDraft, saveDraft } from "../../runtime_storage.js";
import type { RuntimeLanguage } from "../../runtime_i18n.js";
import { translate } from "../../runtime_i18n.js";
import type { SessionLocation, SessionWorkspaceState } from "../state/useSessionWorkspace.js";

type Props = {
  location: SessionLocation;
  session: SessionWorkspaceState;
  language: RuntimeLanguage;
};

const QUICK_MESSAGE_KINDS = [
  { value: "guidance", label: "Guidance" },
  { value: "question", label: "Question" },
  { value: "todo", label: "Todo" },
  { value: "note", label: "Note" },
] as const;

export function SessionComposer({ location, session, language }: Props) {
  const t = (value: string) => translate(value, language);
  const [composer, setComposer] = useState("");
  const [kind, setKind] = useState("note");
  const selectionRef = useRef<HTMLDivElement | null>(null);
  useFlowingSelection(selectionRef, kind);
  const [priority, setPriority] = useState("normal");
  const [requiresAck, setRequiresAck] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState("");
  const [replyTo, setReplyTo] = useState("");
  const [replyPreview, setReplyPreview] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const draftScope = useRef({ revision: 0, pending: false });
  const reviseDraft = () => { draftScope.current.revision += 1; };
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    draftScope.current = { revision: 0, pending: false };
    setSubmitting(false);
    setComposer(loadDraft(location.projectId, location.sessionId));
    setEditingMessageId("");
    setReplyTo("");
    setReplyPreview("");
    return () => { draftScope.current = { revision: 0, pending: false }; };
  }, [location.projectId, location.sessionId]);

  useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<{ messageId?: string; message?: string }>;
      if (!custom.detail?.messageId) return;
      reviseDraft();
      setEditingMessageId(custom.detail.messageId);
      setReplyTo("");
      setReplyPreview("");
      setComposer(custom.detail.message || "");
    };
    window.addEventListener("webcodex-runtime-edit-message", handler);
    return () => window.removeEventListener("webcodex-runtime-edit-message", handler);
  }, []);

  useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<{ messageId?: string; message?: string }>;
      if (!custom.detail?.messageId) return;
      reviseDraft();
      setEditingMessageId("");
      setReplyTo(custom.detail.messageId);
      setReplyPreview(custom.detail.message || "");
      saveDraft(location.projectId, location.sessionId, composer);
    };
    window.addEventListener("webcodex-runtime-reply-message", handler);
    return () => window.removeEventListener("webcodex-runtime-reply-message", handler);
  }, [composer, location.projectId, location.sessionId]);


  useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<{ kind?: string }>;
      const nextKind = custom.detail?.kind;
      if (nextKind && QUICK_MESSAGE_KINDS.some((item) => item.value === nextKind)) setKind(nextKind);
      reviseDraft();
      setEditingMessageId("");
      setReplyTo("");
      setReplyPreview("");
      saveDraft(location.projectId, location.sessionId, composer);
      window.setTimeout(() => textareaRef.current?.focus(), 0);
    };
    window.addEventListener("webcodex-runtime-compose-message", handler);
    return () => window.removeEventListener("webcodex-runtime-compose-message", handler);
  }, [composer, location.projectId, location.sessionId]);
  const submit = async () => {
    const scope = draftScope.current;
    if (!composer.trim() || session.sending || scope.pending) return;
    const revision = scope.revision;
    scope.pending = true;
    setSubmitting(true);
    try {
      const ok = editingMessageId
        ? await session.replace(editingMessageId, composer)
        : await session.send({ message: composer, kind, priority, requiresAck, replyTo: replyTo || undefined });
      if (!ok || draftScope.current !== scope || scope.revision !== revision) return;
      if (!editingMessageId) clearDraft(location.projectId, location.sessionId);
      setComposer("");
      setEditingMessageId("");
      setReplyTo("");
      setReplyPreview("");
    } finally {
      scope.pending = false;
      if (draftScope.current === scope) setSubmitting(false);
    }
  };

  const cancelEdit = () => {
    reviseDraft();
    setEditingMessageId("");
    setComposer(loadDraft(location.projectId, location.sessionId));
  };

  const cancelReply = () => {
    reviseDraft();
    setReplyTo("");
    setReplyPreview("");
  };

  return (
    <div className="composer-row">
      <div className="composer">
        <div className="composer-heading">
          <div>
            <strong>{t("Collaborate with this Session")}</strong>
            <small>{t("Leave retained guidance, questions, todos, or notes for the next turn.")}</small>
          </div>
        </div>
        {editingMessageId && (
          <div className="composer-context">
            <span>{t("Editing retained message")}</span>
            <button type="button" onClick={cancelEdit} aria-label={t("Cancel edit")}><X size={14} /></button>
          </div>
        )}
        {replyTo && !editingMessageId && (
          <div className="composer-context">
            <span>{t("Replying to")}: {replyPreview.slice(0, 120)}</span>
            <button type="button" onClick={cancelReply} aria-label={t("Cancel reply")}><X size={14} /></button>
          </div>
        )}
        {session.mutationNotice && <div className="composer-notice" role="status">{t(session.mutationNotice)}</div>}
        <textarea
          ref={textareaRef}
          aria-label={t("Send a message to this work session…")}
          placeholder={t("Send a message to this work session…")}
          rows={1}
          value={composer}
          onChange={(event) => {
            reviseDraft();
            setComposer(event.target.value);
            if (!editingMessageId) saveDraft(location.projectId, location.sessionId, event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <div className="composer-footer">
          <div className="composer-controls">
            <div ref={selectionRef} className="composer-kind-tabs" aria-label={t("Message kind")}>
              {QUICK_MESSAGE_KINDS.map((item) => (
                <button
                  key={item.value}
                  className={kind === item.value ? "active" : ""}
                  aria-pressed={kind === item.value}
                  type="button"
                  onClick={() => { reviseDraft(); setKind(item.value); }}
                >
                  {t(item.label)}
                </button>
              ))}
            </div>
            <details className="composer-options">
              <summary>{t("Options")}</summary>
              <div className="composer-options-popover">
                <label>
                  {t("Kind")}
                  <select value={kind} onChange={(event) => { reviseDraft(); setKind(event.target.value); }}>
                    <option value="note">{t("Note")}</option>
                    <option value="progress">{t("Progress")}</option>
                    <option value="guidance">{t("Guidance")}</option>
                    <option value="question">{t("Question")}</option>
                    <option value="risk">{t("Risk")}</option>
                    <option value="todo">{t("Todo")}</option>
                  </select>
                </label>
                <label>
                  {t("Priority")}
                  <select value={priority} onChange={(event) => { reviseDraft(); setPriority(event.target.value); }}>
                    <option value="normal">normal</option>
                    <option value="high">high</option>
                  </select>
                </label>
                <label className="checkbox-line">
                  <input type="checkbox" checked={requiresAck} onChange={(event) => { reviseDraft(); setRequiresAck(event.target.checked); }} />
                  {t("Requires acknowledgement")}
                </label>
              </div>
            </details>
          </div>
          <button
            className="send-button"
            type="button"
            onClick={() => void submit()}
            disabled={!composer.trim() || session.sending || submitting}
            aria-label={editingMessageId ? t("Save") : t("Send")}
          >
            {session.sending || submitting ? <LoaderCircle size={16} /> : editingMessageId ? <Check size={16} /> : <ArrowUpRight size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}
