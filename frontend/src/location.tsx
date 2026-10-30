import React, { createContext, useContext, useEffect, useState } from "react";
import { Platform, Modal, View, Text, TouchableOpacity, StyleSheet, Linking } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api } from "@/src/api";
import { colors, spacing, radius } from "@/src/theme";

type PricingLoc = {
  postal: string | null;
  city: string | null;
  fsa: string | null;
  zoneName: string | null;
  surchargeCents: number;
  ready: boolean;
};

type PricingCtx = PricingLoc & {
  /** Admin toggle — controls the "Your location detected — City" banner. */
  locationMode: boolean;
  /** True when we could NOT determine the customer's location → grocery prices are hidden. */
  gated: boolean;
  refresh: () => void;
  /** Open the "how to enable location" help popup. */
  showHelp: () => void;
};

const DEFAULT: PricingLoc = { postal: null, city: null, fsa: null, zoneName: null, surchargeCents: 0, ready: false };
const Ctx = createContext<PricingCtx>({ ...DEFAULT, locationMode: false, gated: false, refresh: () => {}, showHelp: () => {} });
const CACHE_KEY = "pricing_location_v1";

async function getCoords(): Promise<{ lat: number; lng: number } | null> {
  try {
    if (Platform.OS === "web") {
      if (typeof navigator === "undefined" || !navigator.geolocation) return null;
      return await new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
          (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
          () => resolve(null),
          { timeout: 8000, maximumAge: 600000 },
        );
      });
    }
    const Location = await import("expo-location");
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") return null;
    const pos = await Location.getCurrentPositionAsync({});
    return { lat: pos.coords.latitude, lng: pos.coords.longitude };
  } catch {
    return null;
  }
}

export function PricingLocationProvider({ children }: { children: React.ReactNode }) {
  const [loc, setLoc] = useState<PricingLoc>(DEFAULT);
  const [locationMode, setLocationMode] = useState(false);
  const [priceGating, setPriceGating] = useState(false);
  const [helpVisible, setHelpVisible] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const resolve = async () => {
    try {
      const cachedRaw = await AsyncStorage.getItem(CACHE_KEY);
      if (cachedRaw) {
        const c = JSON.parse(cachedRaw);
        setLoc({ ...c, ready: true });
      }
    } catch {}
    const coords = await getCoords();
    if (!coords) {
      setLoc((p) => ({ ...p, ready: true }));
      return;
    }
    const r = await api.post<{ postal_code: string | null; city: string | null; fsa: string | null; zone_name: string | null; surcharge_cents: number }>(
      "/pricing/resolve",
      { lat: coords.lat, lng: coords.lng },
    );
    if (r.ok) {
      const next: PricingLoc = {
        postal: r.data.postal_code,
        city: r.data.city || null,
        fsa: r.data.fsa,
        zoneName: r.data.zone_name,
        surchargeCents: r.data.surcharge_cents || 0,
        ready: true,
      };
      setLoc(next);
      try { await AsyncStorage.setItem(CACHE_KEY, JSON.stringify(next)); } catch {}
    } else {
      setLoc((p) => ({ ...p, ready: true }));
    }
  };

  useEffect(() => {
    resolve();
    (async () => {
      const s = await api.get<{ location_banner_enabled?: boolean; price_gating_enabled?: boolean }>("/settings");
      if (s.ok) {
        setLocationMode(s.data?.location_banner_enabled === true);
        setPriceGating(s.data?.price_gating_enabled === true);
      }
    })();
  }, []);

  const retry = async () => {
    setRetrying(true);
    await resolve();
    setRetrying(false);
    // Close only if we now have a location.
    setLoc((p) => {
      if (p.postal) setHelpVisible(false);
      return p;
    });
  };

  // Grocery prices are hidden only when price-gating is enabled by admin AND
  // we don't have a resolved location. Default (gating off) → prices always show.
  const gated = priceGating && !loc.postal;

  return (
    <Ctx.Provider value={{ ...loc, locationMode, gated, refresh: resolve, showHelp: () => setHelpVisible(true) }}>
      {children}
      <Modal visible={helpVisible} transparent animationType="fade" onRequestClose={() => setHelpVisible(false)}>
        <View style={styles.backdrop}>
          <View style={styles.sheet} testID="location-help-modal">
            <View style={styles.iconCircle}>
              <Ionicons name="location" size={26} color={colors.primary} />
            </View>
            <Text style={styles.title}>Turn on location to see grocery prices</Text>
            <Text style={styles.body}>
              We use your location to show accurate grocery prices and delivery for your area. Grocery prices stay hidden until location is on. (Meal-plan prices are always visible.)
            </Text>

            <View style={styles.steps}>
              {(Platform.OS === "web"
                ? [
                    "Tap the lock / location icon in your browser's address bar",
                    "Choose “Allow” for Location",
                    "Then tap “Try again” below",
                  ]
                : Platform.OS === "ios"
                ? [
                    "Open Settings → Privacy & Security → Location Services",
                    "Find this app and choose “While Using the App”",
                    "Return here and tap “Try again”",
                  ]
                : [
                    "Open Settings → Apps → this app → Permissions",
                    "Enable the Location permission",
                    "Return here and tap “Try again”",
                  ]
              ).map((s, i) => (
                <View key={i} style={styles.stepRow}>
                  <View style={styles.stepNum}><Text style={styles.stepNumText}>{i + 1}</Text></View>
                  <Text style={styles.stepText}>{s}</Text>
                </View>
              ))}
            </View>

            <TouchableOpacity testID="location-help-retry" style={styles.primaryBtn} onPress={retry} disabled={retrying}>
              <Ionicons name="refresh" size={18} color="#fff" />
              <Text style={styles.primaryBtnText}>{retrying ? "Checking…" : "Try again"}</Text>
            </TouchableOpacity>

            {Platform.OS !== "web" && (
              <TouchableOpacity style={styles.secondaryBtn} onPress={() => Linking.openSettings()}>
                <Ionicons name="settings-outline" size={18} color={colors.primary} />
                <Text style={styles.secondaryBtnText}>Open Settings</Text>
              </TouchableOpacity>
            )}

            <TouchableOpacity testID="location-help-close" style={styles.closeBtn} onPress={() => setHelpVisible(false)}>
              <Text style={styles.closeBtnText}>Close</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </Ctx.Provider>
  );
}

export function usePricingLocation() {
  return useContext(Ctx);
}

/** Append the detected postal to a query string so backend applies the zone surcharge. */
export function withPostal(path: string, postal: string | null): string {
  if (!postal) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}postal=${encodeURIComponent(postal)}`;
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center", padding: spacing.lg },
  sheet: { width: "100%", maxWidth: 420, backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.xl, gap: spacing.md, alignItems: "center" },
  iconCircle: { width: 56, height: 56, borderRadius: 28, backgroundColor: colors.surfaceAlt, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 19, fontWeight: "800", color: colors.text, textAlign: "center" },
  body: { fontSize: 14, color: colors.textMuted, textAlign: "center", lineHeight: 20 },
  steps: { alignSelf: "stretch", gap: 10, marginVertical: 4 },
  stepRow: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  stepNum: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center", marginTop: 1 },
  stepNumText: { color: "#fff", fontSize: 12, fontWeight: "800" },
  stepText: { flex: 1, fontSize: 13.5, color: colors.text, lineHeight: 19 },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, alignSelf: "stretch", backgroundColor: colors.primary, borderRadius: radius.pill, height: 50 },
  primaryBtnText: { color: "#fff", fontSize: 15, fontWeight: "800" },
  secondaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, alignSelf: "stretch", backgroundColor: colors.surfaceAlt, borderRadius: radius.pill, height: 48 },
  secondaryBtnText: { color: colors.primary, fontSize: 14, fontWeight: "800" },
  closeBtn: { paddingVertical: 6 },
  closeBtnText: { color: colors.textMuted, fontSize: 14, fontWeight: "700" },
});
