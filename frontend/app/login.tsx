import React from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Image,
} from "react-native";
import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import Ionicons from "@react-native-vector-icons/ionicons";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "@/src/auth";
import { spacing, radius, shadows } from "@/src/theme";
import { BRAND } from "@/src/brand";
import { EmailAuthModal } from "@/src/components/EmailAuthModal";

const LOGO = require("../assets/brand/logo-circle.png");
const LOGIN_BG = require("../assets/brand/hero-fresh.jpg");

// Deep-blue photo overlay (from the logo palette) — keeps the grocery photo
// visible up top while making the text fully readable below. These stay fixed
// regardless of light/dark theme, so they're literal blues.
const OVERLAY = ["rgba(4,28,64,0.30)", "rgba(3,20,50,0.72)", "rgba(1,13,34,0.95)"] as const;

export default function LoginScreen() {
  const { signIn, signInAsGuest, loading, user } = useAuth();
  const router = useRouter();
  const [signingIn, setSigningIn] = React.useState(false);
  const [guestLoading, setGuestLoading] = React.useState(false);
  const [emailOpen, setEmailOpen] = React.useState(false);

  React.useEffect(() => {
    if (!loading && user) router.replace("/(tabs)");
  }, [loading, user, router]);

  const onSignIn = async () => {
    setSigningIn(true);
    try { await signIn(); } finally { setSigningIn(false); }
  };

  const onGuest = async () => {
    setGuestLoading(true);
    try { await signInAsGuest(); } finally { setGuestLoading(false); }
  };

  return (
    <View style={styles.root} testID="login-screen">
      <Image
        source={LOGIN_BG}
        blurRadius={2}
        style={StyleSheet.absoluteFill}
        resizeMode="cover"
      />
      <LinearGradient
        colors={OVERLAY}
        locations={[0, 0.52, 1]}
        style={StyleSheet.absoluteFill}
      />
      <SafeAreaView edges={["top", "bottom"]} style={styles.safeInner}>
        <View style={styles.brandRow}>
          <View style={styles.logoBadge}>
            <Image source={LOGO} style={styles.logoImg} resizeMode="contain" />
          </View>
          <Text style={styles.brand} testID="login-brand-name">{BRAND.name}</Text>
        </View>

        <View style={styles.bottom}>
          <View style={styles.eyebrowPill} testID="login-tagline">
            <Ionicons name="leaf" size={12} color="#0B1E3F" />
            <Text style={styles.eyebrowPillText}>HALAL · FRESH · DELIVERED</Text>
          </View>
          <Text style={styles.title}>Groceries delivered{"\n"}to your door.</Text>
          <Text style={styles.subtitle}>
            Fresh halal meat, fish, sweets & everyday essentials — hand-picked and delivered
            across the Greater Toronto Area.
          </Text>

          <TouchableOpacity
            testID="login-google-button"
            onPress={onSignIn}
            disabled={signingIn || guestLoading}
            activeOpacity={0.85}
            style={styles.googleBtn}
          >
            {signingIn ? (
              <ActivityIndicator color="#000" />
            ) : (
              <>
                <Ionicons name="logo-google" size={20} color="#000" />
                <Text style={styles.googleBtnText}>Continue with Google</Text>
              </>
            )}
          </TouchableOpacity>

          <TouchableOpacity
            testID="login-email-button"
            onPress={() => setEmailOpen(true)}
            disabled={signingIn || guestLoading}
            activeOpacity={0.85}
            style={styles.emailBtn}
          >
            <Ionicons name="mail-outline" size={18} color="#fff" />
            <Text style={styles.guestBtnText}>Login with Email</Text>
          </TouchableOpacity>

          <TouchableOpacity
            testID="login-guest-button"
            onPress={onGuest}
            disabled={signingIn || guestLoading}
            activeOpacity={0.85}
            style={styles.guestBtn}
          >
            {guestLoading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="person-outline" size={18} color="#fff" />
                <Text style={styles.guestBtnText}>Continue as guest</Text>
              </>
            )}
          </TouchableOpacity>

          <Text style={styles.legal}>By continuing you agree to our Terms & Privacy Policy.</Text>

          <TouchableOpacity
            testID="delivery-partner-entry"
            onPress={() => router.push("/delivery-partner")}
            style={styles.deliveryLink}
          >
            <Ionicons name="bicycle-outline" size={14} color="rgba(255,255,255,0.9)" />
            <Text style={styles.deliveryLinkText}>Delivery partner? Sign in here →</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
      <EmailAuthModal visible={emailOpen} onClose={() => setEmailOpen(false)} onSuccess={() => { setEmailOpen(false); router.replace("/(tabs)"); }} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#011838" },
  safeInner: { flex: 1, justifyContent: "space-between", padding: spacing.xl },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  logoBadge: {
    width: 52, height: 52, borderRadius: radius.pill,
    overflow: "hidden", backgroundColor: "#fff",
    borderWidth: 2, borderColor: "rgba(255,255,255,0.85)",
    alignItems: "center", justifyContent: "center",
    ...shadows.card,
  },
  logoImg: { width: "82%", height: "82%" },
  brand: { fontSize: 22, fontWeight: "800", letterSpacing: 0.3, color: "#fff" },
  bottom: { gap: spacing.md },
  eyebrowPill: {
    alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#F5D06B", paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: radius.pill,
  },
  eyebrowPillText: { color: "#0B1E3F", letterSpacing: 1.5, fontSize: 10.5, fontWeight: "900" },
  title: { color: "#fff", fontSize: 40, fontWeight: "800", lineHeight: 44, letterSpacing: -0.5 },
  subtitle: { color: "rgba(255,255,255,0.85)", fontSize: 15, lineHeight: 22, marginTop: spacing.sm },
  googleBtn: {
    marginTop: spacing.xl,
    backgroundColor: "#fff",
    borderRadius: radius.pill,
    paddingVertical: 16,
    paddingHorizontal: spacing.xl,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    ...shadows.card,
  },
  googleBtnText: { fontSize: 16, fontWeight: "700", color: "#111" },
  guestBtn: {
    marginTop: spacing.md,
    backgroundColor: "rgba(255,255,255,0.14)",
    borderRadius: radius.pill,
    paddingVertical: 14,
    paddingHorizontal: spacing.xl,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.4)",
  },
  guestBtnText: { fontSize: 15, fontWeight: "700", color: "#fff" },
  emailBtn: {
    marginTop: spacing.md,
    backgroundColor: "rgba(255,255,255,0.14)",
    borderRadius: radius.pill,
    paddingVertical: 14,
    paddingHorizontal: spacing.xl,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.4)",
  },
  deliveryLink: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.md, paddingVertical: 10 },
  deliveryLinkText: { color: "rgba(255,255,255,0.92)", fontSize: 13, fontWeight: "800", textDecorationLine: "underline" },
  legal: {
    color: "rgba(255,255,255,0.6)", fontSize: 11, textAlign: "center", marginTop: spacing.md,
  },
});
