import React from "react";
import { View, ScrollView } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "@/src/theme";
import { ShopHeader } from "@/src/components/ShopHeader";
import { ShopFooter } from "@/src/components/ShopFooter";
import { ThaliOrderBody } from "@/src/components/ThaliOrderBody";

/** Desktop-web Thali Party Order page with full site chrome. */
export default function ShopThali() {
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ShopHeader />
      <ScrollView contentContainerStyle={{ alignItems: "center" }}>
        <View style={{ width: "100%", maxWidth: 1200 }}>
          <ThaliOrderBody web bottomInset={insets.bottom} />
        </View>
        <ShopFooter />
      </ScrollView>
    </View>
  );
}
