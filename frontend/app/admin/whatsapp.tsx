/**
 * Admin WhatsApp Inbox — conversations grouped by customer phone, thread
 * view, reply box.
 *
 * Free-form replies work ONLY inside the 24-hour customer-service window
 * (24h after the customer's last message). The UI disables the reply box
 * when the window is closed; the backend enforces the same rule with 403.
 * No AI bot, no auto-reply — a human admin sends every reply.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator,
} from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import AdminShell from "@/src/components/AdminShell";
import { adminApi } from "@/src/adminApi";
import { colors, spacing, radius, shadows } from "@/src/theme";

type Conv = {
  phone: string; name: string; last_body: string; last_at: string | null;
  last_direction: string; window_expires_at: string | null; window_open: boolean;
};
type Msg = {
  message_id: string; direction: string; from_phone: string; to_phone: string;
  body: string; template_name: string | null; status: string;
  created_at: string | null; window_expires_at: string | null;
};
type Thread = {
  phone: string; name: string; window_open: boolean;
  window_expires_at: string | null; messages: Msg[];
};

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString();
}

export default function WhatsappInbox() {
  const [convs, setConvs] = useState<Conv[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [thread, setThread] = useState<Thread | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; msg: string } | null>(null);

  const loadConvs = async () => {
    setLoading(true);
    const r = await adminApi.get<Conv[]>("/admin/whatsapp/conversations");
    if (r.ok) setConvs(r.data);
    setLoading(false);
  };

  useEffect(() => { loadConvs(); }, []);

  const openThread = async (phone: string) => {
    setSelected(phone);
    setThreadLoading(true);
    setNotice(null);
    const r = await adminApi.get<Thread>(`/admin/whatsapp/thread?phone=${encodeURIComponent(phone)}`);
    setThreadLoading(false);
    if (r.ok) setThread(r.data);
    else setNotice({ ok: false, msg: r.error });
  };

  const sendReply = async () => {
    if (!selected || !reply.trim() || sending) return;
    setSending(true);
    setNotice(null);
    const r = await adminApi.post<any>("/admin/whatsapp/reply", { to: selected, body: reply.trim() });
    setSending(false);
    if (r.ok) {
      setReply("");
      setNotice({ ok: true, msg: `✓ Reply sent — status: ${r.data?.status || "queued"}` });
      await openThread(selected);
      await loadConvs();
    } else {
      setNotice({ ok: false, msg: r.error });
    }
  };

  return (
    <AdminShell title="WhatsApp Inbox">
      {loading ? (
        <ActivityIndicator color={colors.primary} />
      ) : selected && thread ? (
        <View style={{ gap: spacing.md }}>
          <TouchableOpacity testID="wa-back" onPress={() => { setSelected(null); setThread(null); }}
            style={{ flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start" }}>
            <Ionicons name="arrow-back" size={16} color={colors.primary} />
            <Text style={{ color: colors.primary, fontWeight: "800" }}>All conversations</Text>
          </TouchableOpacity>

          <View style={styles.threadHead}>
            <Text style={styles.threadName}>{thread.name || thread.phone}</Text>
            {!!thread.name && <Text style={styles.threadPhone}>{thread.phone}</Text>}
            {!thread.window_open ? (
              <View testID="wa-window-banner" style={[styles.banner, styles.bannerWarn]}>
                <Ionicons name="time-outline" size={16} color="#B45309" />
                <Text style={styles.bannerText}>
                  24-hour window closed — free-form replies are not allowed for this customer.
                  Send an approved template from the Broadcast screen instead.
                </Text>
              </View>
            ) : (
              <Text style={styles.windowOk}>
                24-hour window open
                {thread.window_expires_at ? ` · until ${fmtTime(thread.window_expires_at)}` : ""}
              </Text>
            )}
          </View>

          <View testID="wa-thread" style={{ gap: spacing.sm }}>
            {thread.messages.length === 0 && (
              <Text style={{ color: colors.textMuted }}>No messages in this thread yet.</Text>
            )}
            {thread.messages.map((m) => {
              const inbound = m.direction === "inbound";
              return (
                <View key={m.message_id}
                  style={[styles.bubble, inbound ? styles.bubbleIn : styles.bubbleOut]}>
                  <Text style={styles.bubbleBody}>{m.body}</Text>
                  {!!m.template_name && (
                    <Text style={styles.templateTag}>Template: {m.template_name}</Text>
                  )}
                  <Text style={styles.bubbleMeta}>
                    {inbound ? "Customer" : "You"} · {fmtTime(m.created_at)}
                    {!inbound && m.status ? ` · ${m.status}` : ""}
                  </Text>
                </View>
              );
            })}
          </View>

          <View style={{ gap: spacing.sm }}>
            <TextInput
              testID="wa-reply-input"
              value={reply} onChangeText={setReply}
              placeholder={thread.window_open ? "Type a reply…" : "Window closed — replies disabled"}
              multiline editable={thread.window_open}
              style={[styles.input, { minHeight: 80 }, !thread.window_open && { opacity: 0.5 }]}
            />
            <TouchableOpacity testID="wa-reply-send"
              onPress={sendReply}
              disabled={!thread.window_open || sending || !reply.trim()}
              style={[styles.btnPrimary, (!thread.window_open || sending || !reply.trim()) && { opacity: 0.5 }]}>
              {sending ? <ActivityIndicator color="#fff" size="small" /> :
                <><Ionicons name="send-outline" size={14} color="#fff" /><Text style={styles.btnPrimaryText}>Send reply</Text></>}
            </TouchableOpacity>
          </View>

          {notice && (
            <View style={[styles.banner, notice.ok ? styles.bannerOk : styles.bannerFail]}>
              <Ionicons name={notice.ok ? "checkmark-circle" : "alert-circle"} size={16}
                color={notice.ok ? colors.success : colors.danger} />
              <Text style={styles.bannerText}>{notice.msg}</Text>
            </View>
          )}
        </View>
      ) : (
        <View testID="wa-conv-list" style={{ gap: spacing.sm }}>
          {convs.length === 0 && (
            <Text style={{ color: colors.textMuted }}>
              No WhatsApp messages yet. When a customer texts the WhatsApp sender,
              their conversation appears here.
            </Text>
          )}
          {convs.map((c) => (
            <TouchableOpacity key={c.phone} testID="wa-conv-item" onPress={() => openThread(c.phone)}
              style={styles.convRow}>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.convName}>{c.name || c.phone}</Text>
                {!!c.name && <Text style={styles.convPhone}>{c.phone}</Text>}
                <Text style={styles.convLast} numberOfLines={1}>
                  {c.last_direction === "outbound" ? "You: " : ""}{c.last_body}
                </Text>
              </View>
              <View style={{ alignItems: "flex-end", gap: 4 }}>
                <Text style={styles.convTime}>{fmtTime(c.last_at)}</Text>
                <View style={[styles.windowDot, { backgroundColor: c.window_open ? colors.success : colors.textMuted }]}>
                  <Text style={styles.windowDotText}>{c.window_open ? "Window open" : "Window closed"}</Text>
                </View>
              </View>
            </TouchableOpacity>
          ))}
          {threadLoading && <ActivityIndicator color={colors.primary} />}
          {notice && (
            <View style={[styles.banner, styles.bannerFail]}>
              <Ionicons name="alert-circle" size={16} color={colors.danger} />
              <Text style={styles.bannerText}>{notice.msg}</Text>
            </View>
          )}
        </View>
      )}
    </AdminShell>
  );
}

const styles = StyleSheet.create({
  convRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.md, ...shadows.soft },
  convName: { color: colors.text, fontWeight: "800", fontSize: 15 },
  convPhone: { color: colors.textMuted, fontSize: 12 },
  convLast: { color: colors.textMuted, fontSize: 13, marginTop: 2 },
  convTime: { color: colors.textMuted, fontSize: 11 },
  windowDot: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  windowDotText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  threadHead: { gap: 4 },
  threadName: { color: colors.text, fontWeight: "800", fontSize: 18 },
  threadPhone: { color: colors.textMuted, fontSize: 13 },
  windowOk: { color: colors.success, fontSize: 12, fontWeight: "700" },
  bubble: { maxWidth: "85%", padding: spacing.md, borderRadius: radius.lg, gap: 4 },
  bubbleIn: { backgroundColor: colors.surfaceAlt, alignSelf: "flex-start" },
  bubbleOut: { backgroundColor: "#DCFCE7", alignSelf: "flex-end" },
  bubbleBody: { color: colors.text, fontSize: 15, lineHeight: 21 },
  templateTag: { color: colors.textMuted, fontSize: 11, fontWeight: "700" },
  bubbleMeta: { color: colors.textMuted, fontSize: 11 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 10, color: colors.text, fontSize: 16 },
  btnPrimary: { flexDirection: "row", gap: 6, alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, paddingHorizontal: 16, paddingVertical: 12, borderRadius: radius.pill },
  btnPrimaryText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  banner: { flexDirection: "row", alignItems: "flex-start", gap: 6, padding: 10, borderRadius: radius.md, borderWidth: 1 },
  bannerWarn: { backgroundColor: "#FEF3C7", borderColor: "#F59E0B" },
  bannerOk: { backgroundColor: "#ecfdf5", borderColor: "#a7f3d0" },
  bannerFail: { backgroundColor: "#fef2f2", borderColor: "#fecaca" },
  bannerText: { color: colors.text, fontSize: 12, flex: 1, lineHeight: 17 },
});
