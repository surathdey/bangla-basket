import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";
import { colors } from "@/src/theme";

export default function Index() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (user) {
      // After a web Google login, Emergent returns to "/" — send shop visitors
      // back to the shop page they came from instead of the app tabs.
      let dest: any = "/(tabs)";
      try {
        const ret = typeof window !== "undefined" ? window.sessionStorage.getItem("bb_return_to") : null;
        if (ret && ret.startsWith("/shop")) dest = ret;
        if (typeof window !== "undefined") window.sessionStorage.removeItem("bb_return_to");
      } catch {}
      router.replace(dest);
    } else router.replace("/login");
  }, [loading, user, router]);

  return (
    <View style={styles.container} testID="root-loader">
      <ActivityIndicator size="large" color={colors.primary} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, alignItems: "center", justifyContent: "center" },
});
