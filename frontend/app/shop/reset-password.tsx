import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, shadows } from "@/src/theme";

export default function ResetPassword() {
  const params = useLocalSearchParams<{ token?: string }>();
  const token = typeof params.token === "string" ? params.token : "";
  const { resetPassword } = useAuth();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const submit = async () => {
    setError("");
    if (!token) { setError("This reset link is invalid."); return; }
    if (password.length < 8) { setError("Password must be at least 8 characters."); return; }
    if (password !== confirm) { setError("Passwords don't match."); return; }
    setBusy(true);
    const r = await resetPassword(token, password);
    setBusy(false);
    if (r.ok) setDone(true); else setError(r.error || "This reset link is invalid or has expired.");
  };

  return (
    <View style={styles.page}>
      <View style={styles.card} testID="reset-password-card">
        <View style={styles.iconCircle}><Ionicons name="lock-closed" size={26} color={colors.primary} /></View>
        {done ? (
          <>
            <Text style={styles.title}>Password updated</Text>
            <Text style={styles.hint}>You can now log in with your new password.</Text>
            <TouchableOpacity testID="reset-goto-shop" style={styles.primary} onPress={() => router.replace("/shop")}>
              <Text style={styles.primaryText}>Back to shop</Text>
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Text style={styles.title}>Choose a new password</Text>
            <Text style={styles.hint}>Enter a new password for your Bangla Basket account.</Text>
            <TextInput testID="reset-password" style={styles.input} placeholder="New password (min 8)" placeholderTextColor={colors.textMuted} secureTextEntry autoCapitalize="none" value={password} onChangeText={setPassword} />
            <TextInput testID="reset-confirm" style={styles.input} placeholder="Confirm new password" placeholderTextColor={colors.textMuted} secureTextEntry autoCapitalize="none" value={confirm} onChangeText={setConfirm} onSubmitEditing={submit} />
            {!!error && <Text style={styles.error}>{error}</Text>}
            <TouchableOpacity testID="reset-submit" style={[styles.primary, busy && { opacity: 0.5 }]} disabled={busy} onPress={submit}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>Set new password</Text>}
            </TouchableOpacity>
          </>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.background, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  card: { width: "100%", maxWidth: 420, backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.xl, gap: spacing.md, alignItems: "center", ...shadows.soft },
  iconCircle: { width: 56, height: 56, borderRadius: 28, backgroundColor: colors.surfaceAlt, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 20, fontWeight: "800", color: colors.text, textAlign: "center" },
  hint: { fontSize: 14, color: colors.textMuted, textAlign: "center", lineHeight: 20 },
  input: { alignSelf: "stretch", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 14, fontSize: 16, color: colors.text, backgroundColor: colors.background },
  error: { color: colors.danger, fontSize: 13, fontWeight: "600" },
  primary: { alignSelf: "stretch", backgroundColor: colors.primary, borderRadius: radius.pill, height: 52, alignItems: "center", justifyContent: "center" },
  primaryText: { color: "#fff", fontSize: 16, fontWeight: "800" },
});
