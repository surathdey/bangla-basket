import React, { useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, Modal, ActivityIndicator } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius } from "@/src/theme";
import { EmailAuthModal } from "@/src/components/EmailAuthModal";

const INK = "#011838";

/** Top-right login/account control for the web storefront. No login gate. */
export function ShopAccountButton({ compact = false }: { compact?: boolean }) {
  const { user, signIn, signInAsGuest } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const loggedIn = user && user.role !== "guest";
  const display = loggedIn ? (user!.name || user!.email.split("@")[0]) : null;

  if (loggedIn) {
    return (
      <TouchableOpacity testID="shop-account-btn" style={styles.accountPill} onPress={() => router.push("/shop/account")}>
        <Ionicons name="person-circle" size={20} color={INK} />
        {!compact && <Text style={styles.accountText} numberOfLines={1}>{display}</Text>}
      </TouchableOpacity>
    );
  }

  return (
    <>
      <TouchableOpacity testID="shop-login-btn" style={styles.loginBtn} onPress={() => setOpen(true)}>
        <Ionicons name="person-outline" size={16} color={INK} />
        {!compact && <Text style={styles.loginText}>Login</Text>}
      </TouchableOpacity>

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <TouchableOpacity activeOpacity={1} style={styles.backdrop} onPress={() => setOpen(false)}>
          <TouchableOpacity activeOpacity={1} style={styles.card} testID="shop-login-modal">
            <View style={styles.headerRow}>
              <Text style={styles.title}>Sign in to Bangla Basket</Text>
              <TouchableOpacity onPress={() => setOpen(false)}><Ionicons name="close" size={24} color={colors.textMuted} /></TouchableOpacity>
            </View>
            <Text style={styles.hint}>Save addresses, track orders, earn loyalty points & use coupons.</Text>

            <TouchableOpacity testID="web-google-btn" style={styles.google} onPress={() => { setOpen(false); signIn(); }}>
              <Ionicons name="logo-google" size={18} color="#111" />
              <Text style={styles.googleText}>Continue with Google</Text>
            </TouchableOpacity>

            <TouchableOpacity testID="web-email-btn" style={styles.secondary} onPress={() => { setOpen(false); setEmailOpen(true); }}>
              <Ionicons name="mail-outline" size={18} color={INK} />
              <Text style={styles.secondaryText}>Login with Email</Text>
            </TouchableOpacity>

            <TouchableOpacity testID="web-guest-btn" style={styles.guest} disabled={busy} onPress={async () => { setBusy(true); await signInAsGuest(); setBusy(false); setOpen(false); }}>
              {busy ? <ActivityIndicator color={colors.textMuted} /> : <Text style={styles.guestText}>Continue as guest</Text>}
            </TouchableOpacity>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>

      <EmailAuthModal visible={emailOpen} onClose={() => setEmailOpen(false)} onSuccess={() => { setEmailOpen(false); router.push("/shop/account"); }} />
    </>
  );
}

const styles = StyleSheet.create({
  loginBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#fff", borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 8 },
  loginText: { color: INK, fontSize: 13, fontWeight: "800" },
  accountPill: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#fff", borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 6, maxWidth: 160 },
  accountText: { color: INK, fontSize: 13, fontWeight: "800" },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", padding: spacing.lg },
  card: { width: "100%", maxWidth: 400, backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.xl, gap: spacing.md },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { fontSize: 18, fontWeight: "800", color: colors.text },
  hint: { fontSize: 13, color: colors.textMuted, lineHeight: 19 },
  google: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, backgroundColor: "#fff", borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, height: 50 },
  googleText: { fontSize: 15, fontWeight: "700", color: "#111" },
  secondary: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, backgroundColor: colors.surfaceAlt, borderRadius: radius.pill, height: 50 },
  secondaryText: { fontSize: 15, fontWeight: "800", color: INK },
  guest: { alignItems: "center", justifyContent: "center", height: 44 },
  guestText: { fontSize: 14, fontWeight: "700", color: colors.textMuted, textDecorationLine: "underline" },
});
