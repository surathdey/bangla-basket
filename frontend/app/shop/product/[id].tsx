import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, spacing } from "@/src/theme";
import { ShopHeader } from "@/src/components/ShopHeader";
import { ShopFooter } from "@/src/components/ShopFooter";
import { track } from "@/src/analytics";
import { ProductDetailBody } from "@/src/components/ProductDetailBody";

/** Desktop-web product detail page — full site chrome (header, breadcrumb,
 *  footer). The mobile app keeps using /grocery/[id]. */
export default function ShopProduct() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [crumb, setCrumb] = useState<{ category: string; title: string }>({ category: "", title: "" });

  // Anonymous launch analytics — page view, fire-and-forget.
  useEffect(() => {
    if (id) track("page_view", { path: `/shop/product/${id}` });
  }, [id]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ShopHeader active="groceries" />
      <ScrollView contentContainerStyle={{ alignItems: "center" }}>
        {/* Breadcrumb */}
        <View style={styles.crumbWrap}>
          <View style={styles.crumbRow}>
            <Text style={styles.crumbLink} onPress={() => router.push("/shop")}>Home</Text>
            <Text style={styles.crumbSep}>/</Text>
            <Text style={styles.crumbLink} onPress={() => router.push({ pathname: "/shop/browse", params: crumb.category ? { category: crumb.category } : {} })}>
              {crumb.category || "Groceries"}
            </Text>
            {!!crumb.title && (
              <>
                <Text style={styles.crumbSep}>/</Text>
                <Text style={styles.crumbCurrent} numberOfLines={1}>{crumb.title}</Text>
              </>
            )}
          </View>
        </View>

        <View style={{ width: "100%", maxWidth: 1200 }}>
          <ProductDetailBody
            id={String(id)}
            web
            bottomInset={insets.bottom}
            onLoaded={(g) => setCrumb({ category: g.category || "", title: g.title || "" })}
          />
        </View>

        <ShopFooter />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  crumbWrap: { width: "100%", maxWidth: 1200, paddingHorizontal: spacing.xl, paddingTop: spacing.lg },
  crumbRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6 },
  crumbLink: { color: colors.primary, fontSize: 13, fontWeight: "700" },
  crumbSep: { color: colors.textMuted, fontSize: 13 },
  crumbCurrent: { color: colors.textMuted, fontSize: 13, fontWeight: "600", flexShrink: 1 },
});
