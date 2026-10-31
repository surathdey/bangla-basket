import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, useWindowDimensions } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { BRAND } from "@/src/brand";
import { spacing, radius } from "@/src/theme";
import { ShopLogo } from "@/src/components/ShopHeader";

const BLUE = "#1E5AA8";
const INK = "#1F2D45";
const MUTE = "#6B7280";

// Business details shown in the storefront footer.
const CONTACT = { email: BRAND.support?.email || "hello@banglabasket.ca", phone: "+1 365-397-9453" };
const HOURS = ["Mon – Fri: 9:00 AM – 8:00 PM", "Saturday: 9:00 AM – 6:00 PM", "Sunday: 10:00 AM – 4:00 PM"];
const ADDRESS = ["Bangla Basket Fulfilment centre @ Mississauga", "3050 Confederation Parkway, Mississauga, ON L5B 3Z6"];

/** One shared, content-rich storefront footer used on every /shop page. */
export function ShopFooter() {
  const { width } = useWindowDimensions();
  const router = useRouter();
  const isNarrow = width < 760;
  const contentWidth = Math.min(width, 1200);

  const links: { label: string; onPress: () => void }[] = [
    { label: "Home", onPress: () => router.push("/shop") },
    { label: "Groceries", onPress: () => router.push("/shop/browse") },
    { label: "Meal Plans", onPress: () => router.push("/shop/meal-plans") },
  ];

  return (
    <View style={styles.footer} testID="shop-footer">
      <View style={[styles.inner, { width: contentWidth }]}>
        <View style={[styles.cols, isNarrow && styles.colsNarrow]}>
          {/* Brand */}
          <View style={isNarrow ? styles.brandColNarrow : styles.brandCol}>
            <ShopLogo size={56} border={4} />
            <Text style={styles.brandName}>{BRAND.name}</Text>
            <Text style={styles.tagline}>Your neighbourhood halal grocery & weekly meal plans — fresh, delivered across {BRAND.region.serviceArea}.</Text>
            <View style={styles.linkRow}>
              {links.map((l, i) => (
                <React.Fragment key={l.label}>
                  {i > 0 && <Text style={styles.dot}>·</Text>}
                  <Text style={styles.link} onPress={l.onPress}>{l.label}</Text>
                </React.Fragment>
              ))}
            </View>
          </View>

          {/* Contact */}
          <View style={isNarrow ? styles.colNarrow : styles.col}>
            <Text style={styles.colHead}>Contact</Text>
            <TouchableOpacity style={styles.row} onPress={() => {}}>
              <Ionicons name="mail-outline" size={14} color={BLUE} />
              <Text style={styles.rowText}>{CONTACT.email}</Text>
            </TouchableOpacity>
            <View style={styles.row}>
              <Ionicons name="call-outline" size={14} color={BLUE} />
              <Text style={styles.rowText}>{CONTACT.phone}</Text>
            </View>
          </View>

          {/* Hours */}
          <View style={isNarrow ? styles.colNarrow : styles.col}>
            <Text style={styles.colHead}>Business Hours</Text>
            {HOURS.map(h => (
              <View key={h} style={styles.row}>
                <Ionicons name="time-outline" size={14} color={BLUE} />
                <Text style={styles.rowText}>{h}</Text>
              </View>
            ))}
          </View>

          {/* Address */}
          <View style={isNarrow ? styles.colNarrow : styles.col}>
            <Text style={styles.colHead}>Address</Text>
            <View style={styles.row}>
              <Ionicons name="location-outline" size={14} color={BLUE} style={{ marginTop: 2 }} />
              <View style={{ flex: 1 }}>
                {ADDRESS.map(a => <Text key={a} style={styles.rowText}>{a}</Text>)}
              </View>
            </View>
          </View>
        </View>

        <View style={styles.bottomBar}>
          <Text style={styles.copy}>© {new Date().getFullYear()} {BRAND.legalName || BRAND.name}. All rights reserved.</Text>
          <Text style={styles.copy}>All prices in CA$ (Canadian dollars).</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  footer: { backgroundColor: "#fff", borderTopWidth: 1, borderTopColor: "#F0E6D8", alignItems: "center", paddingVertical: spacing.xl, marginTop: spacing.xl },
  inner: { paddingHorizontal: spacing.lg, gap: spacing.lg },
  cols: { flexDirection: "row", justifyContent: "space-between", gap: spacing.xl, flexWrap: "wrap" },
  // Mobile: plain full-width blocks, no flex sizing — the old flex+wrap row
  // collapsed on phones so the Contact heading overlapped the links row.
  colsNarrow: { flexDirection: "column", flexWrap: "nowrap", gap: spacing.xl },
  brandCol: { flex: 1.4, minWidth: 240, gap: 6 },
  brandColNarrow: { width: "100%", gap: 6 },
  brandName: { fontSize: 19, fontWeight: "900", color: INK, marginTop: 6 },
  tagline: { fontSize: 13, color: MUTE, lineHeight: 19, maxWidth: 360 },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap" },
  link: { color: BLUE, fontWeight: "700", fontSize: 13 },
  dot: { color: MUTE },
  col: { flex: 1, minWidth: 170, gap: 8 },
  colNarrow: { width: "100%", gap: 8 },
  colHead: { fontSize: 11, fontWeight: "900", letterSpacing: 1.5, color: INK, marginBottom: 2 },
  row: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  rowText: { fontSize: 13, color: MUTE, lineHeight: 19, flexShrink: 1 },
  bottomBar: { borderTopWidth: 1, borderTopColor: "#F0E6D8", paddingTop: spacing.md, marginTop: spacing.sm, flexDirection: "row", justifyContent: "space-between", flexWrap: "wrap", gap: 6 },
  copy: { fontSize: 12, color: MUTE },
});
