import React, { useEffect, useState } from "react";
import {
  Modal, View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView,
} from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius } from "@/src/theme";

type Mode = "login" | "signup" | "forgot";

/** Email + password auth: login, sign up, and forgot-password. */
export function EmailAuthModal({ visible, onClose, onSuccess }: {
  visible: boolean; onClose: () => void; onSuccess: () => void;
}) {
  const { loginEmail, signUpEmail, forgotPassword } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!visible) { setMode("login"); setName(""); setEmail(""); setPassword(""); setError(""); setNotice(""); setBusy(false); }
  }, [visible]);

  const emailOk = /^\S+@\S+\.\S+$/.test(email.trim());

  const submit = async () => {
    setError(""); setNotice("");
    if (!emailOk) { setError("Enter a valid email address."); return; }
    if (mode !== "forgot" && password.length < 8) { setError("Password must be at least 8 characters."); return; }
    setBusy(true);
    if (mode === "login") {
      const r = await loginEmail(email, password);
      setBusy(false);
      if (r.ok) onSuccess(); else setError(r.error || "Incorrect email or password.");
    } else if (mode === "signup") {
      const r = await signUpEmail(email, password, name.trim() || undefined);
      setBusy(false);
      if (r.ok) onSuccess(); else setError(r.error || "Could not create your account.");
    } else {
      const r = await forgotPassword(email);
      setBusy(false);
      setNotice(r.message || "If an account exists, a reset link has been sent.");
    }
  };

  const title = mode === "login" ? "Login with Email" : mode === "signup" ? "Create your account" : "Reset your password";

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.backdrop}>
        <View style={styles.sheet} testID="email-auth-modal">
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: spacing.md }}>
            <View style={styles.headerRow}>
              <Text style={styles.title}>{title}</Text>
              <TouchableOpacity onPress={onClose} testID="auth-close"><Ionicons name="close" size={24} color={colors.textMuted} /></TouchableOpacity>
            </View>

            {mode === "signup" && (
              <TextInput testID="auth-name" style={styles.input} placeholder="Your name (optional)" placeholderTextColor={colors.textMuted} value={name} onChangeText={setName} />
            )}
            <TextInput
              testID="auth-email" style={styles.input} placeholder="you@example.com" placeholderTextColor={colors.textMuted}
              autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail}
            />
            {mode !== "forgot" && (
              <TextInput
                testID="auth-password" style={styles.input} placeholder="Password (min 8 characters)" placeholderTextColor={colors.textMuted}
                secureTextEntry autoCapitalize="none" value={password} onChangeText={setPassword} onSubmitEditing={submit}
              />
            )}

            {!!error && <Text style={styles.error}>{error}</Text>}
            {!!notice && <Text style={styles.notice}>{notice}</Text>}

            <TouchableOpacity testID="auth-submit" style={[styles.primary, busy && styles.disabled]} disabled={busy} onPress={submit}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>{mode === "login" ? "Log in" : mode === "signup" ? "Sign up" : "Send reset link"}</Text>}
            </TouchableOpacity>

            {mode === "login" && (
              <View style={{ gap: 10, alignItems: "center" }}>
                <TouchableOpacity testID="auth-goto-forgot" onPress={() => { setMode("forgot"); setError(""); }}>
                  <Text style={styles.link}>Forgot password?</Text>
                </TouchableOpacity>
                <TouchableOpacity testID="auth-goto-signup" onPress={() => { setMode("signup"); setError(""); }}>
                  <Text style={styles.linkMuted}>New here? <Text style={styles.link}>Create an account</Text></Text>
                </TouchableOpacity>
              </View>
            )}
            {mode === "signup" && (
              <TouchableOpacity testID="auth-goto-login" onPress={() => { setMode("login"); setError(""); }} style={{ alignItems: "center" }}>
                <Text style={styles.linkMuted}>Already have an account? <Text style={styles.link}>Log in</Text></Text>
              </TouchableOpacity>
            )}
            {mode === "forgot" && (
              <TouchableOpacity testID="auth-back-login" onPress={() => { setMode("login"); setNotice(""); }} style={{ alignItems: "center" }}>
                <Text style={styles.link}>Back to login</Text>
              </TouchableOpacity>
            )}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl, padding: spacing.xl, maxWidth: 480, width: "100%", alignSelf: "center", maxHeight: "88%", paddingBottom: spacing.xxl },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { fontSize: 20, fontWeight: "800", color: colors.text },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 14, fontSize: 16, color: colors.text, backgroundColor: colors.background },
  error: { color: colors.danger, fontSize: 13, fontWeight: "600" },
  notice: { color: colors.success, fontSize: 13, fontWeight: "600" },
  primary: { backgroundColor: colors.primary, borderRadius: radius.pill, height: 52, alignItems: "center", justifyContent: "center" },
  primaryText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  disabled: { opacity: 0.5 },
  link: { color: colors.primary, fontSize: 14, fontWeight: "800" },
  linkMuted: { color: colors.textMuted, fontSize: 14, fontWeight: "600" },
});
