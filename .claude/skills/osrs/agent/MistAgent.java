import java.awt.*;
import java.awt.event.*;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.List;
import javax.swing.SwingUtilities;

/**
 * MIST in-process input agent for the Alora RuneLite client.
 * Loaded at launch via -javaagent. Opens a localhost socket and injects
 * AWT KeyEvents / MouseEvents straight into the game Canvas, bypassing
 * macOS key-window focus routing (so keyboard works while backgrounded).
 *
 * Eyes (screencapture -l) and background mouse (CGEventPostToPid) live on the
 * host side; this agent exists to solve the one thing those can't: keyboard.
 */
public class MistAgent {
    static volatile Canvas canvas;

    public static void premain(String args, java.lang.instrument.Instrumentation inst) {
        log("MistAgent premain loaded");
        Thread t = new Thread(MistAgent::serve, "mist-agent");
        t.setDaemon(true);
        t.start();
        Thread m = new Thread(MistAgent::muteLoop, "mist-mute");
        m.setDaemon(true);
        m.start();
    }

    // Auto-enforce silence: re-apply mute whenever logged in. Music volume is a synced preference
    // that a track change can re-raise and setMusicVolume doesn't persist, so a one-shot isn't
    // enough; this keeps her instance silent across track changes AND re-logins (the client JVM
    // persists, so this thread outlives individual game sessions). Cheap + idempotent.
    static volatile boolean autoMute = true;
    static void muteLoop() {
        while (true) {
            try {
                Thread.sleep(30000); // volumes rarely need re-asserting; 30s keeps the client thread quiet
                if (autoMute && gamestate().contains("LOGGED_IN")) mute("");
            } catch (Throwable ignore) {}
        }
    }

    static void log(String s) { System.err.println("[mist-agent] " + s); }

    static void serve() {
        try (ServerSocket ss = new ServerSocket()) {
            ss.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 43210));
            log("listening on 127.0.0.1:43210");
            while (true) {
                try (Socket s = ss.accept();
                     BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream()));
                     PrintWriter out = new PrintWriter(s.getOutputStream(), true)) {
                    String line = in.readLine();
                    if (line != null) out.println(handle(line.trim()));
                } catch (Exception e) { log("conn err: " + e); }
            }
        } catch (Exception e) { log("server err: " + e); }
    }

    static String handle(String cmd) {
        try {
            if (cmd.equals("ping")) return "pong";
            if (cmd.equals("find")) { Canvas c = findCanvas(); return c == null ? "NO_CANVAS" : "CANVAS " + c.getWidth() + "x" + c.getHeight() + " focusable=" + c.isFocusable() + " showing=" + c.isShowing(); }
            if (cmd.equals("info")) return inventory();
            if (cmd.equals("tree")) return tree();
            if (cmd.startsWith("clickcomp ")) return clickComp(cmd.substring(10).trim());
            if (cmd.equals("gamestate")) return gamestate();
            if (cmd.equals("state")) return state();
            if (cmd.equals("npcs")) return npcs();
            if (cmd.equals("stats")) return stats();
            if (cmd.equals("hp")) return hp();
            if (cmd.equals("inv")) return inv();
            if (cmd.equals("eat")) return eat();
            if (cmd.equals("players")) return players();
            if (cmd.equals("target")) return target();
            if (cmd.startsWith("threats")) { String w = cmd.length() > 7 ? cmd.substring(7).trim() : "*"; return threats(w.isEmpty() ? "*" : w); }
            if (cmd.startsWith("automute ")) { autoMute = cmd.substring(9).trim().equalsIgnoreCase("on"); return "OK automute=" + autoMute; }
            if (cmd.equals("vols")) return vols();
            if (cmd.equals("mute") || cmd.startsWith("mute ")) return mute(cmd.length() > 4 ? cmd.substring(4).trim() : "");
            if (cmd.equals("roots")) return roots();
            if (cmd.startsWith("widgetkids ")) return widgetkids(cmd.substring(11).trim());
            if (cmd.startsWith("widgettree ")) return widgetTree(cmd.substring(11).trim());
            if (cmd.startsWith("clickpath ")) return clickPath(cmd.substring(10).trim());
            if (cmd.startsWith("clickwidget ")) return clickWidget(cmd.substring(12).trim());
            if (cmd.startsWith("clicknpc ")) return clickNpc(cmd.substring(9).trim());
            if (cmd.startsWith("type ")) { typeText(cmd.substring(5)); return "OK typed " + (cmd.length() - 5) + " chars"; }
            if (cmd.equals("clear")) { for (int i = 0; i < 32; i++) specialKey("BACKSPACE"); return "OK clear"; }
            if (cmd.startsWith("key ")) { specialKey(cmd.substring(4).trim()); return "OK key " + cmd.substring(4).trim(); }
            if (cmd.startsWith("click ")) { String[] p = cmd.substring(6).trim().split("\\s+"); humanClick(Integer.parseInt(p[0]), Integer.parseInt(p[1])); return "OK click " + p[0] + "," + p[1]; }
            if (cmd.startsWith("rclick ")) { String[] p = cmd.substring(7).trim().split("\\s+"); clickCanvas(Integer.parseInt(p[0]), Integer.parseInt(p[1])); return "OK rclick " + p[0] + "," + p[1]; }
            if (cmd.startsWith("hmove ")) { String[] p = cmd.substring(6).trim().split("\\s+"); humanMove(Integer.parseInt(p[0]), Integer.parseInt(p[1])); return "OK hmove " + p[0] + "," + p[1]; }
            return "UNKNOWN " + cmd;
        } catch (Exception e) { return "ERR " + e; }
    }

    static String inventory() {
        StringBuilder sb = new StringBuilder();
        for (Frame f : Frame.getFrames()) {
            sb.append("FRAME '").append(f.getTitle()).append("' ").append(f.getWidth()).append("x").append(f.getHeight()).append(" showing=").append(f.isShowing()).append("; ");
            collect(f, sb, 0);
        }
        return sb.length() == 0 ? "NO_FRAMES" : sb.toString();
    }
    static void collect(Container c, StringBuilder sb, int d) {
        for (Component k : c.getComponents()) {
            if (k instanceof Canvas) sb.append("[Canvas ").append(k.getWidth()).append("x").append(k.getHeight()).append(" showing=").append(k.isShowing()).append("] ");
            if (k instanceof Container && d < 6) collect((Container) k, sb, d + 1);
        }
    }

    static String tree() {
        StringBuilder sb = new StringBuilder();
        for (Frame f : Frame.getFrames()) { if (!f.isShowing()) continue; sb.append("=FRAME '").append(f.getTitle()).append("'\n"); dump(f, sb, 1); }
        return sb.length() == 0 ? "NO_SHOWING_FRAMES" : sb.toString();
    }
    static void dump(Container c, StringBuilder sb, int d) {
        for (Component k : c.getComponents()) {
            String txt = "";
            if (k instanceof javax.swing.AbstractButton) txt = "btn'" + ((javax.swing.AbstractButton) k).getText() + "'";
            else if (k instanceof javax.swing.JLabel) txt = "lbl'" + ((javax.swing.JLabel) k).getText() + "'";
            Rectangle r = k.getBounds();
            for (int i = 0; i < d; i++) sb.append(' ');
            sb.append(k.getClass().getSimpleName()).append(' ').append(r.width).append('x').append(r.height).append(" show=").append(k.isShowing()).append(' ').append(txt).append('\n');
            if (k instanceof Container && d < 8) dump((Container) k, sb, d + 1);
        }
    }

    static String clickComp(String sub) throws Exception {
        final String needle = sub.toLowerCase();
        Component match = null;
        for (Frame f : Frame.getFrames()) { if (!f.isShowing()) continue; match = search(f, needle); if (match != null) break; }
        if (match == null) return "NO_MATCH";
        final Component c = match;
        onEdt(() -> {
            if (c instanceof javax.swing.AbstractButton) { ((javax.swing.AbstractButton) c).doClick(); }
            else {
                int x = c.getWidth() / 2, y = c.getHeight() / 2; long t = System.currentTimeMillis();
                c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_PRESSED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
                c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_RELEASED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
                c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_CLICKED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
            }
        });
        return "OK clickcomp " + c.getClass().getSimpleName();
    }
    static Component search(Container c, String needle) {
        for (Component k : c.getComponents()) {
            String txt = null;
            if (k instanceof javax.swing.AbstractButton) txt = ((javax.swing.AbstractButton) k).getText();
            else if (k instanceof javax.swing.JLabel) txt = ((javax.swing.JLabel) k).getText();
            if (txt != null && txt.toLowerCase().contains(needle)) return k;
            if (k instanceof Container) { Component r = search((Container) k, needle); if (r != null) return r; }
        }
        return null;
    }

    // ---- RuneLite game-state reflection ----
    static Object CLIENT;
    static Object client() throws Exception {
        if (CLIENT != null) return CLIENT;
        Class<?> rl = Class.forName("net.runelite.client.RuneLite");
        Object inj = rl.getMethod("getInjector").invoke(null);
        // get getInstance from the PUBLIC Injector interface (impl class is non-public -> IllegalAccess)
        java.lang.reflect.Method gi = Class.forName("com.google.inject.Injector").getMethod("getInstance", Class.class);
        gi.setAccessible(true);
        CLIENT = gi.invoke(inj, Class.forName("net.runelite.api.Client"));
        return CLIENT;
    }
    // RuneLite's ClientThread (from the injector). The official client (1.12.x) guards widget
    // reads like getCanvasLocation with "must be called on client thread"; we hop onto it.
    static Object CLIENTTHREAD;
    static Object clientThread() throws Exception {
        if (CLIENTTHREAD != null) return CLIENTTHREAD;
        Class<?> rl = Class.forName("net.runelite.client.RuneLite");
        Object inj = rl.getMethod("getInjector").invoke(null);
        java.lang.reflect.Method gi = Class.forName("com.google.inject.Injector").getMethod("getInstance", Class.class);
        gi.setAccessible(true);
        CLIENTTHREAD = gi.invoke(inj, Class.forName("net.runelite.client.callback.ClientThread"));
        return CLIENTTHREAD;
    }
    // Run a task synchronously on the client thread (queue via ClientThread.invoke + latch for the result).
    @SuppressWarnings("unchecked")
    static <T> T onClient(java.util.concurrent.Callable<T> task) throws Exception {
        final Object[] box = new Object[2];   // [0]=result [1]=throwable
        final java.util.concurrent.CountDownLatch latch = new java.util.concurrent.CountDownLatch(1);
        Runnable r = () -> { try { box[0] = task.call(); } catch (Throwable t) { box[1] = t; } finally { latch.countDown(); } };
        Object ct = clientThread();
        Class.forName("net.runelite.client.callback.ClientThread").getMethod("invoke", Runnable.class).invoke(ct, r);
        if (!latch.await(6, java.util.concurrent.TimeUnit.SECONDS)) throw new IllegalStateException("client-thread timeout");
        if (box[1] != null) throw new Exception((Throwable) box[1]);
        return (T) box[0];
    }

    // invoke a no/var-arg method (matched by name + arg count) declared on the given interface/class
    static Object call(Object target, String cls, String method, Object... args) throws Exception {
        Class<?> c = Class.forName(cls);
        for (java.lang.reflect.Method m : c.getMethods())
            if (m.getName().equals(method) && m.getParameterCount() == args.length) return m.invoke(target, args);
        throw new NoSuchMethodException(cls + "." + method + "/" + args.length);
    }
    static int planeOf(Object cl) throws Exception { return (int) call(cl, "net.runelite.api.Client", "getPlane"); }

    static String gamestate() {
        try {
            Object cl = client();
            Object gs = call(cl, "net.runelite.api.Client", "getGameState");
            return gs == null ? "null" : gs.toString();   // STARTING/LOGIN_SCREEN/LOGGING_IN/LOADING/LOGGED_IN/...
        } catch (Throwable t) { return "GS_ERR " + t; }
    }

    static String state() {
        try {
            Object cl = client();
            Object lp = call(cl, "net.runelite.api.Client", "getLocalPlayer");
            if (lp == null) return "NO_PLAYER (not logged in / loading)";
            Object wp = call(lp, "net.runelite.api.Actor", "getWorldLocation");
            int x = (int) call(wp, "net.runelite.api.coords.WorldPoint", "getX");
            int y = (int) call(wp, "net.runelite.api.coords.WorldPoint", "getY");
            int p = (int) call(wp, "net.runelite.api.coords.WorldPoint", "getPlane");
            Object nm = call(lp, "net.runelite.api.Actor", "getName");
            Object hp = "?"; try { hp = call(lp, "net.runelite.api.Actor", "getHealthRatio"); } catch (Exception ignore) {}
            return "PLAYER name=" + nm + " world=" + x + "," + y + "," + p;
        } catch (Throwable t) { return "STATE_ERR " + t; }
    }

    static java.lang.reflect.Method L2C;
    static int[] canvasPt(Object cl, Object localPoint, int plane) throws Exception {
        if (L2C == null) {
            Class<?> persp = Class.forName("net.runelite.api.Perspective");
            for (java.lang.reflect.Method m : persp.getMethods())
                if (m.getName().equals("localToCanvas") && m.getParameterCount() == 3 && m.getParameterTypes()[2] == int.class) { L2C = m; break; }
        }
        Object pt = L2C.invoke(null, cl, localPoint, plane);
        if (pt == null) return null;
        // RuneLite returns net.runelite.api.Point (getX/getY methods); java.awt.Point has x/y fields
        int x, y;
        try { x = (int) pt.getClass().getMethod("getX").invoke(pt); y = (int) pt.getClass().getMethod("getY").invoke(pt); }
        catch (NoSuchMethodException e) { x = pt.getClass().getField("x").getInt(pt); y = pt.getClass().getField("y").getInt(pt); }
        if (x < 0 || y < 0) return null;   // off-screen sentinel
        return new int[]{x, y};
    }

    static String npcs() {
        try {
            Object cl = client();
            int plane = planeOf(cl);
            Object list = call(cl, "net.runelite.api.Client", "getNpcs");
            java.util.List<?> ns = (java.util.List<?>) list;
            StringBuilder sb = new StringBuilder();
            int n = 0;
            for (Object npc : ns) {
                if (npc == null) continue;
                Object nm = call(npc, "net.runelite.api.Actor", "getName");
                Object loc = call(npc, "net.runelite.api.Actor", "getLocalLocation");
                if (loc == null) continue;
                int[] pt = canvasPt(cl, loc, plane);
                if (pt == null) continue;             // off-screen
                sb.append(nm).append("@").append(pt[0]).append(",").append(pt[1]).append("; ");
                if (++n > 60) break;
            }
            return sb.length() == 0 ? "NO_NPCS_ON_SCREEN" : sb.toString();
        } catch (Throwable t) { return "NPCS_ERR " + t; }
    }

    static String clickNpc(String namePart) {
        try {
            Object cl = client();
            int plane = planeOf(cl);
            java.util.List<?> ns = (java.util.List<?>) call(cl, "net.runelite.api.Client", "getNpcs");
            String needle = namePart.toLowerCase();
            Object best = null; int[] bestPt = null;
            for (Object npc : ns) {
                if (npc == null) continue;
                Object nm = call(npc, "net.runelite.api.Actor", "getName");
                if (nm == null || !nm.toString().toLowerCase().contains(needle)) continue;
                Object loc = call(npc, "net.runelite.api.Actor", "getLocalLocation");
                if (loc == null) continue;
                int[] pt = canvasPt(cl, loc, plane);
                if (pt == null) continue;
                best = nm; bestPt = pt; break;
            }
            if (bestPt == null) return "NPC_NOT_FOUND_ONSCREEN " + namePart;
            humanClick(bestPt[0], bestPt[1]);
            return "OK clicknpc '" + best + "' @" + bestPt[0] + "," + bestPt[1];
        } catch (Throwable t) { return "CLICKNPC_ERR " + t; }
    }

    // ---- combat reads: skills / hp / inventory / players / threats ----
    // precise-typed reflective invoke (call() matches by arg-count only, which is
    // ambiguous for overloads taking an enum vs an int — these need exact types).
    static Object callT(Object target, String cls, String method, Class<?>[] types, Object... args) throws Exception {
        return Class.forName(cls).getMethod(method, types).invoke(target, args);
    }
    static Object skillEnum(String name) throws Exception {
        @SuppressWarnings({"unchecked", "rawtypes"})
        Object v = Enum.valueOf((Class) Class.forName("net.runelite.api.Skill"), name);
        return v;
    }

    static String stats() {
        try {
            Object cl = client();
            Class<?> skCls = Class.forName("net.runelite.api.Skill");
            java.lang.reflect.Method gr = Class.forName("net.runelite.api.Client").getMethod("getRealSkillLevel", skCls);
            java.lang.reflect.Method gb = Class.forName("net.runelite.api.Client").getMethod("getBoostedSkillLevel", skCls);
            String[] names = {"ATTACK", "STRENGTH", "DEFENCE", "HITPOINTS", "RANGED", "MAGIC", "PRAYER"};
            StringBuilder sb = new StringBuilder();
            for (String n : names) {
                Object s = skillEnum(n);
                sb.append(n.substring(0, 3)).append("=").append(gb.invoke(cl, s)).append("/").append(gr.invoke(cl, s)).append(" ");
            }
            return sb.toString().trim();
        } catch (Throwable t) { return "STATS_ERR " + t; }
    }

    static String hp() {
        try {
            Object cl = client();
            Class<?> skCls = Class.forName("net.runelite.api.Skill");
            Object HP = skillEnum("HITPOINTS");
            int cur = (int) callT(cl, "net.runelite.api.Client", "getBoostedSkillLevel", new Class[]{skCls}, HP);
            int max = (int) callT(cl, "net.runelite.api.Client", "getRealSkillLevel", new Class[]{skCls}, HP);
            return "HP " + cur + " " + max;
        } catch (Throwable t) { return "HP_ERR " + t; }
    }

    static Object inventoryContainer(Object cl) throws Exception {
        Class<?> invId = Class.forName("net.runelite.api.InventoryID");
        @SuppressWarnings({"unchecked", "rawtypes"})
        Object INV = Enum.valueOf((Class) invId, "INVENTORY");
        return callT(cl, "net.runelite.api.Client", "getItemContainer", new Class[]{invId}, INV);
    }
    static String itemName(Object cl, int id) {
        try {
            java.lang.reflect.Method m;
            try { m = Class.forName("net.runelite.api.Client").getMethod("getItemDefinition", int.class); }
            catch (NoSuchMethodException e) { m = Class.forName("net.runelite.api.Client").getMethod("getItemComposition", int.class); }
            Object comp = m.invoke(cl, id);
            return String.valueOf(comp.getClass().getMethod("getName").invoke(comp)).replace(' ', '_');
        } catch (Throwable t) { return "item" + id; }
    }
    static String inv() {
        try {
            Object cl = client();
            Object inv = inventoryContainer(cl);
            if (inv == null) return "NO_INV";
            Object[] items = (Object[]) Class.forName("net.runelite.api.ItemContainer").getMethod("getItems").invoke(inv);
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < items.length; i++) {
                Object it = items[i];
                int id = (int) it.getClass().getMethod("getId").invoke(it);
                if (id <= 0) continue;
                int q = (int) it.getClass().getMethod("getQuantity").invoke(it);
                sb.append(i).append(":").append(id).append(":").append(itemName(cl, id)).append("x").append(q).append("; ");
            }
            return sb.length() == 0 ? "EMPTY_INV" : sb.toString();
        } catch (Throwable t) { return "INV_ERR " + t; }
    }

    // common training/PvM foods (substring match against item names, lowercased)
    static final String[] FOOD = {"shrimp", "sardine", "herring", "anchovies", "trout", "pike", "salmon",
        "tuna", "cod", "lobster", "bass", "swordfish", "monkfish", "shark", "manta", "sea_turtle",
        "anglerfish", "karambwan", "bread", "cake", "_pie", "pizza", "cooked", "stew", "curry",
        "potato", "wine", "kebab", "jug_of_wine"};
    static boolean isFood(String nm) {
        String n = nm.toLowerCase();
        for (String f : FOOD) if (n.contains(f)) return true;
        return false;
    }

    // RuneLite getWidget(group, child) across fixed/resizable inventory ids; return the one with item children
    static Object inventoryWidget(Object cl) throws Exception {
        java.lang.reflect.Method gw = Class.forName("net.runelite.api.Client").getMethod("getWidget", int.class, int.class);
        int[][] ids = {{149, 0}, {161, 0}, {164, 0}};   // fixed, resizable-classic, resizable-modern
        for (int[] gc : ids) {
            Object w = gw.invoke(cl, gc[0], gc[1]);
            if (w == null) continue;
            Object[] kids = (Object[]) w.getClass().getMethod("getDynamicChildren").invoke(w);
            if (kids != null && kids.length > 0) return w;
        }
        return null;
    }
    static int[] widgetCenter(Object w) throws Exception {
        Object loc = w.getClass().getMethod("getCanvasLocation").invoke(w);
        if (loc == null) return null;
        int x = (int) loc.getClass().getMethod("getX").invoke(loc);
        int y = (int) loc.getClass().getMethod("getY").invoke(loc);
        int wd = (int) w.getClass().getMethod("getWidth").invoke(w);
        int ht = (int) w.getClass().getMethod("getHeight").invoke(w);
        if (x < 0 || y < 0) return null;
        return new int[]{x + wd / 2, y + ht / 2};
    }
    static String eat() {
        try {
            Object cl = client();
            Object w = inventoryWidget(cl);
            if (w == null) return "NO_INV_WIDGET";
            Object[] kids = (Object[]) w.getClass().getMethod("getDynamicChildren").invoke(w);
            for (Object k : kids) {
                int id = (int) k.getClass().getMethod("getItemId").invoke(k);
                if (id <= 0) continue;
                if (!isFood(itemName(cl, id).replace('_', ' '))) continue;
                int[] pt = widgetCenter(k);
                if (pt == null) continue;
                clickCanvas(pt[0], pt[1]);
                return "OK eat " + itemName(cl, id) + " @" + pt[0] + "," + pt[1];
            }
            return "NO_FOOD";
        } catch (Throwable t) { return "EAT_ERR " + t; }
    }

    static String players() {
        try {
            Object cl = client();
            int plane = planeOf(cl);
            Object lp = call(cl, "net.runelite.api.Client", "getLocalPlayer");
            java.util.List<?> ps = (java.util.List<?>) call(cl, "net.runelite.api.Client", "getPlayers");
            StringBuilder sb = new StringBuilder();
            int n = 0;
            for (Object p : ps) {
                if (p == null || p == lp) continue;
                Object nm = call(p, "net.runelite.api.Actor", "getName");
                Object loc = call(p, "net.runelite.api.Actor", "getLocalLocation");
                int[] pt = loc == null ? null : canvasPt(cl, loc, plane);
                sb.append(nm).append(pt == null ? "@off" : "@" + pt[0] + "," + pt[1]).append("; ");
                if (++n > 40) break;
            }
            return sb.length() == 0 ? "NO_PLAYERS" : sb.toString();
        } catch (Throwable t) { return "PLAYERS_ERR " + t; }
    }

    static String target() {
        try {
            Object cl = client();
            Object lp = call(cl, "net.runelite.api.Client", "getLocalPlayer");
            if (lp == null) return "NO_PLAYER";
            Object it = call(lp, "net.runelite.api.Actor", "getInteracting");
            if (it == null) return "NONE";
            return "TARGET " + call(it, "net.runelite.api.Actor", "getName");
        } catch (Throwable t) { return "TARGET_ERR " + t; }
    }

    // NPCs currently interacting with (attacking) a player whose name contains <who> ("*" = any player)
    static String threats(String who) {
        try {
            Object cl = client();
            int plane = planeOf(cl);
            java.util.List<?> ns = (java.util.List<?>) call(cl, "net.runelite.api.Client", "getNpcs");
            String needle = who.toLowerCase();
            StringBuilder sb = new StringBuilder();
            for (Object npc : ns) {
                if (npc == null) continue;
                Object it = call(npc, "net.runelite.api.Actor", "getInteracting");
                if (it == null) continue;
                Object tn = call(it, "net.runelite.api.Actor", "getName");
                if (tn == null) continue;
                if (!who.equals("*") && !tn.toString().toLowerCase().contains(needle)) continue;
                Object nm = call(npc, "net.runelite.api.Actor", "getName");
                Object loc = call(npc, "net.runelite.api.Actor", "getLocalLocation");
                int[] pt = loc == null ? null : canvasPt(cl, loc, plane);
                sb.append(nm).append("->").append(tn).append(pt == null ? "@off" : "@" + pt[0] + "," + pt[1]).append("; ");
            }
            return sb.length() == 0 ? "NO_THREATS" : sb.toString();
        } catch (Throwable t) { return "THREATS_ERR " + t; }
    }

    // ---- widget debugging / clicking (calibrate combat-style tab etc.) ----
    static String widgetkids(String a) {
        try { return onClient(() -> widgetkidsImpl(a)); } catch (Throwable t) { return "WIDGETKIDS_ERR " + t; }
    }
    static String widgetkidsImpl(String a) {
      try {
            String[] p = a.split("\\s+");
            int g = Integer.parseInt(p[0]), c = p.length > 1 ? Integer.parseInt(p[1]) : 0;
            Object cl = client();
            Object w = Class.forName("net.runelite.api.Client").getMethod("getWidget", int.class, int.class).invoke(cl, g, c);
            if (w == null) return "NO_WIDGET " + g + "," + c;
            StringBuilder sb = new StringBuilder();
            appendWidget(sb, w, "root");
            Object[] dyn = (Object[]) w.getClass().getMethod("getDynamicChildren").invoke(w);
            if (dyn != null) for (int i = 0; i < dyn.length; i++) appendWidget(sb, dyn[i], "d" + i);
            Object[] st = (Object[]) w.getClass().getMethod("getStaticChildren").invoke(w);
            if (st != null) for (int i = 0; i < st.length; i++) appendWidget(sb, st[i], "s" + i);
            return sb.toString();
        } catch (Throwable t) { return "WIDGETKIDS_ERR " + t; }
    }
    static void appendWidget(StringBuilder sb, Object w, String tag) {
        if (w == null) return;
        try {
            Object loc = w.getClass().getMethod("getCanvasLocation").invoke(w);
            int x = -1, y = -1;
            if (loc != null) { x = (int) loc.getClass().getMethod("getX").invoke(loc); y = (int) loc.getClass().getMethod("getY").invoke(loc); }
            int wd = (int) w.getClass().getMethod("getWidth").invoke(w);
            int ht = (int) w.getClass().getMethod("getHeight").invoke(w);
            Object txt = w.getClass().getMethod("getText").invoke(w);
            int iid = (int) w.getClass().getMethod("getItemId").invoke(w);
            boolean hid = (boolean) w.getClass().getMethod("isHidden").invoke(w);
            sb.append(tag).append("[").append(x).append(",").append(y).append(" ").append(wd).append("x").append(ht)
              .append(hid ? " HID" : "").append(iid > 0 ? " item" + iid : "")
              .append(txt != null && !txt.toString().isEmpty() ? " '" + txt + "'" : "").append("] ");
        } catch (Throwable e) { Throwable r = e; while (r.getCause() != null) r = r.getCause(); sb.append(tag).append("[err:").append(r.getClass().getSimpleName()).append(":").append(r.getMessage()).append("] "); }
    }
    // mute [vol] -> set music + sound-effect + area-sound volume (default 0 = silent) via the
    // official API (Client.setMusicVolume / Preferences.set*Volume). Per-instance, no UI needed,
    // works even while the settings tab is locked (tutorial). Pass a value to restore, e.g. mute 100.
    // read-only volume report (does NOT set) — for verifying the auto-mute daemon
    static String vols() {
        try {
            return onClient(() -> {
                Object cl = client();
                Class<?> C = Class.forName("net.runelite.api.Client");
                Class<?> P = Class.forName("net.runelite.api.Preferences");
                Object prefs = C.getMethod("getPreferences").invoke(cl);
                int mv = (int) C.getMethod("getMusicVolume").invoke(cl);
                int sv = (int) P.getMethod("getSoundEffectVolume").invoke(prefs);
                int av = (int) P.getMethod("getAreaSoundEffectVolume").invoke(prefs);
                return "VOLS music=" + mv + " sfx=" + sv + " area=" + av + " automute=" + autoMute;
            });
        } catch (Throwable t) { return "VOLS_ERR " + t; }
    }
    static String mute(String a) {
        final int v = a.isEmpty() ? 0 : Integer.parseInt(a);
        try {
            return onClient(() -> {
                Object cl = client();
                Class<?> C = Class.forName("net.runelite.api.Client");
                Class<?> P = Class.forName("net.runelite.api.Preferences");
                C.getMethod("setMusicVolume", int.class).invoke(cl, v);
                Object prefs = C.getMethod("getPreferences").invoke(cl);
                P.getMethod("setSoundEffectVolume", int.class).invoke(prefs, v);
                P.getMethod("setAreaSoundEffectVolume", int.class).invoke(prefs, v);
                int mv = (int) C.getMethod("getMusicVolume").invoke(cl);
                int sv = (int) P.getMethod("getSoundEffectVolume").invoke(prefs);
                int av = (int) P.getMethod("getAreaSoundEffectVolume").invoke(prefs);
                return "OK mute music=" + mv + " sfx=" + sv + " area=" + av;
            });
        } catch (Throwable t) { return "MUTE_ERR " + t; }
    }

    // roots -> list currently-loaded, visible interface roots via Client.getWidgetRoots().
    // Each entry: g<group>.<child>[x,y WxH d<dyn> s<static>]. Finds an open interface's group
    // id WITHOUT guessing (e.g. the character creator), so widgettree/clickpath can drive it.
    static String roots() {
        try { return onClient(MistAgent::rootsImpl); } catch (Throwable t) { return "ROOTS_ERR " + t; }
    }
    static String rootsImpl() {
        try {
            Object cl = client();
            Object[] rs = (Object[]) call(cl, "net.runelite.api.Client", "getWidgetRoots");
            if (rs == null) return "NO_ROOTS";
            StringBuilder sb = new StringBuilder();
            for (Object w : rs) {
                if (w == null) continue;
                boolean hid = (boolean) w.getClass().getMethod("isHidden").invoke(w);
                if (hid) continue;
                int id = (int) w.getClass().getMethod("getId").invoke(w);
                Object loc = w.getClass().getMethod("getCanvasLocation").invoke(w);
                int x = -1, y = -1;
                if (loc != null) { x = (int) loc.getClass().getMethod("getX").invoke(loc); y = (int) loc.getClass().getMethod("getY").invoke(loc); }
                int wd = (int) w.getClass().getMethod("getWidth").invoke(w);
                int ht = (int) w.getClass().getMethod("getHeight").invoke(w);
                int nd = 0, ns = 0;
                Object[] dyn = (Object[]) w.getClass().getMethod("getDynamicChildren").invoke(w); if (dyn != null) nd = dyn.length;
                Object[] st = (Object[]) w.getClass().getMethod("getStaticChildren").invoke(w); if (st != null) ns = st.length;
                sb.append("g").append(id >>> 16).append(".").append(id & 0xFFFF)
                  .append("[").append(x).append(",").append(y).append(" ").append(wd).append("x").append(ht)
                  .append(" d").append(nd).append(" s").append(ns).append("] ");
            }
            return sb.length() == 0 ? "NO_VISIBLE_ROOTS" : sb.toString();
        } catch (Throwable t) { return "ROOTS_ERR " + t; }
    }

    // widgettree <group> [child] -> recursive dump of the subtree. Reports only visible, positioned
    // nodes that are actionable/meaningful (have a sprite, text, or menu action). Each node printed as
    // <path>[cx,cy sprN act'..' 'text'] where <path> is dot-separated s/d/n child indices usable by clickpath.
    static String widgetTree(String a) {
        try { return onClient(() -> widgetTreeImpl(a)); } catch (Throwable t) { return "WIDGETTREE_ERR " + t; }
    }
    static String widgetTreeImpl(String a) {
      try {
            String[] p = a.split("\\s+");
            int g = Integer.parseInt(p[0]), c = p.length > 1 ? Integer.parseInt(p[1]) : 0;
            Object cl = client();
            Object w = Class.forName("net.runelite.api.Client").getMethod("getWidget", int.class, int.class).invoke(cl, g, c);
            if (w == null) return "NO_WIDGET " + g + "," + c;
            StringBuilder sb = new StringBuilder();
            walk(sb, w, "");
            return sb.length() == 0 ? "EMPTY" : sb.toString();
        } catch (Throwable t) { return "WIDGETTREE_ERR " + t; }
    }
    static void walk(StringBuilder sb, Object w, String path) throws Exception {
        if (w == null) return;
        boolean hid = (boolean) w.getClass().getMethod("isHidden").invoke(w);
        Object loc = w.getClass().getMethod("getCanvasLocation").invoke(w);
        int x = -1, y = -1;
        if (loc != null) { x = (int) loc.getClass().getMethod("getX").invoke(loc); y = (int) loc.getClass().getMethod("getY").invoke(loc); }
        int wd = (int) w.getClass().getMethod("getWidth").invoke(w);
        int ht = (int) w.getClass().getMethod("getHeight").invoke(w);
        int spr = -1; try { spr = (int) w.getClass().getMethod("getSpriteId").invoke(w); } catch (Exception e) {}
        Object txt = null; try { txt = w.getClass().getMethod("getText").invoke(w); } catch (Exception e) {}
        String act = ""; try { String[] acts = (String[]) w.getClass().getMethod("getActions").invoke(w);
            if (acts != null) for (String s : acts) if (s != null && !s.isEmpty()) { act = s; break; } } catch (Exception e) {}
        boolean meaningful = spr > 0 || (txt != null && !txt.toString().isEmpty()) || !act.isEmpty();
        if (!hid && x >= 0 && meaningful) {
            sb.append(path.isEmpty() ? "root" : path).append("[").append(x + wd / 2).append(",").append(y + ht / 2)
              .append(spr > 0 ? " spr" + spr : "").append(!act.isEmpty() ? " act'" + act + "'" : "")
              .append(txt != null && !txt.toString().isEmpty() ? " '" + txt + "'" : "").append("] ");
        }
        appendKids(sb, w, "getStaticChildren", path, "s");
        appendKids(sb, w, "getDynamicChildren", path, "d");
        appendKids(sb, w, "getNestedChildren", path, "n");
    }
    static void appendKids(StringBuilder sb, Object w, String method, String path, String tag) throws Exception {
        Object[] kids;
        try { kids = (Object[]) w.getClass().getMethod(method).invoke(w); } catch (Exception e) { return; }
        if (kids == null) return;
        String sep = path.isEmpty() ? "" : ".";
        for (int i = 0; i < kids.length; i++) walk(sb, kids[i], path + sep + tag + i);
    }

    // clickpath <group> <child> <path>  -> click canvas center of a nested widget addressed by a
    // dot-separated s/d/n index path (as printed by widgettree), e.g. "clickpath 269 0 s3.d1".
    static String clickPath(String a) {
        try {
            String[] p = a.split("\\s+");
            int g = Integer.parseInt(p[0]), c = Integer.parseInt(p[1]);
            String path = p.length > 2 ? p[2] : "";
            Object res = onClient(() -> {
                Object cl = client();
                Object w = Class.forName("net.runelite.api.Client").getMethod("getWidget", int.class, int.class).invoke(cl, g, c);
                if (w == null) return "NO_WIDGET";
                if (!path.isEmpty()) {
                    for (String step : path.split("\\.")) {
                        char kind = step.charAt(0); int idx = Integer.parseInt(step.substring(1));
                        String method = kind == 's' ? "getStaticChildren" : kind == 'd' ? "getDynamicChildren" : "getNestedChildren";
                        Object[] kids = (Object[]) w.getClass().getMethod(method).invoke(w);
                        if (kids == null || idx >= kids.length) return "NO_CHILD " + step;
                        w = kids[idx];
                    }
                }
                int[] pt = widgetCenter(w);
                return pt == null ? "WIDGET_HIDDEN" : pt;
            });
            if (res instanceof String) return (String) res;
            int[] pt = (int[]) res;
            clickCanvas(pt[0], pt[1]);
            return "OK clickpath @" + pt[0] + "," + pt[1];
        } catch (Throwable t) { return "CLICKPATH_ERR " + t; }
    }

    // clickwidget <group> <child> [dynIndex]  -> click the canvas center of a widget (or a dynamic child)
    static String clickWidget(String a) {
        try {
            String[] p = a.split("\\s+");
            int g = Integer.parseInt(p[0]), c = Integer.parseInt(p[1]);
            int di = p.length > 2 ? Integer.parseInt(p[2]) : -1;
            Object res = onClient(() -> {
                Object cl = client();
                Object w = Class.forName("net.runelite.api.Client").getMethod("getWidget", int.class, int.class).invoke(cl, g, c);
                if (w == null) return "NO_WIDGET";
                if (di >= 0) {
                    Object[] dyn = (Object[]) w.getClass().getMethod("getDynamicChildren").invoke(w);
                    if (dyn == null || di >= dyn.length) return "NO_DYNCHILD";
                    w = dyn[di];
                }
                int[] pt = widgetCenter(w);
                return pt == null ? "WIDGET_HIDDEN" : pt;
            });
            if (res instanceof String) return (String) res;
            int[] pt = (int[]) res;
            clickCanvas(pt[0], pt[1]);
            return "OK clickwidget @" + pt[0] + "," + pt[1];
        } catch (Throwable t) { return "CLICKWIDGET_ERR " + t; }
    }

    static Canvas findCanvas() {
        Canvas best = null; long bestArea = 0;
        for (Frame f : Frame.getFrames()) {
            for (Canvas c : canvasesIn(f)) {
                long a = (long) c.getWidth() * c.getHeight();
                if (c.isShowing() && a > bestArea) { best = c; bestArea = a; }
            }
        }
        canvas = best; return best;
    }
    static List<Canvas> canvasesIn(Container c) {
        List<Canvas> r = new ArrayList<>();
        for (Component k : c.getComponents()) {
            if (k instanceof Canvas) r.add((Canvas) k);
            if (k instanceof Container) r.addAll(canvasesIn((Container) k));
        }
        return r;
    }

    static void onEdt(Runnable r) throws Exception { SwingUtilities.invokeAndWait(r); }

    // human typing: per-key dispatch with variable inter-keystroke cadence (not an instant burst)
    static void typeText(String text) throws Exception {
        final Canvas c = findCanvas();
        if (c == null) throw new IllegalStateException("no canvas");
        for (char ch : text.toCharArray()) {
            final char fch = ch;
            onEdt(() -> {
                long t = System.currentTimeMillis();
                int kc = KeyEvent.getExtendedKeyCodeForChar(fch);
                c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_PRESSED, t, 0, kc, fch));
                c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_TYPED, t, 0, KeyEvent.VK_UNDEFINED, fch));
                c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_RELEASED, t, 0, kc, fch));
            });
            Thread.sleep(55 + RNG.nextInt(110) + (fch == ' ' ? RNG.nextInt(60) : 0));
        }
    }

    static void specialKey(String name) throws Exception {
        final Canvas c = findCanvas();
        if (c == null) throw new IllegalStateException("no canvas");
        int kc; char ch = KeyEvent.CHAR_UNDEFINED;
        switch (name.toUpperCase()) {
            case "ENTER": kc = KeyEvent.VK_ENTER; ch = '\n'; break;
            case "SPACE": kc = KeyEvent.VK_SPACE; ch = ' '; break;
            case "BACKSPACE": kc = KeyEvent.VK_BACK_SPACE; ch = '\b'; break;
            case "TAB": kc = KeyEvent.VK_TAB; ch = '\t'; break;
            case "ESC": kc = KeyEvent.VK_ESCAPE; break;
            case "LEFT": kc = KeyEvent.VK_LEFT; break;       // camera rotate (antiban)
            case "RIGHT": kc = KeyEvent.VK_RIGHT; break;
            case "UP": kc = KeyEvent.VK_UP; break;
            case "DOWN": kc = KeyEvent.VK_DOWN; break;
            default: throw new IllegalArgumentException("unknown key " + name);
        }
        final int fkc = kc; final char fch = ch;
        onEdt(() -> {
            long t = System.currentTimeMillis();
            c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_PRESSED, t, 0, fkc, fch));
            if (fch != KeyEvent.CHAR_UNDEFINED) c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_TYPED, t, 0, KeyEvent.VK_UNDEFINED, fch));
            c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_RELEASED, t, 0, fkc, fch));
        });
    }

    // raw instant click (used for calibration / UI where exactness > realism)
    static void clickCanvas(int x, int y) throws Exception {
        final Canvas c = findCanvas();
        if (c == null) throw new IllegalStateException("no canvas");
        onEdt(() -> {
            long t = System.currentTimeMillis();
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_MOVED, t, 0, x, y, 0, false));
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_PRESSED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_RELEASED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_CLICKED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
        });
    }

    // ---- behavioral humanization: human-like mouse paths + click dynamics ----
    // The client samples mouse position/motion; straight teleport-clicks at exact tile
    // centers are a bot tell. We move along a WindMouse curve (gravity+wind, ease in/out),
    // pause a human reaction beat, press with a short dwell, and land slightly off-centre.
    static final java.util.Random RNG = new java.util.Random();
    static volatile double curX = 382, curY = 250;        // tracked virtual cursor (canvas space)
    static double rnd() { return RNG.nextDouble(); }
    static int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

    // WindMouse (Benjamin Land): human-like path from (sx,sy) to (dx,dy) as a list of points.
    static java.util.List<int[]> windMouse(double sx, double sy, double dx, double dy) {
        double G = 9, W = 3, M = 15, D = 12;              // gravity, wind, max-step, dist-threshold
        double sqrt3 = Math.sqrt(3), sqrt5 = Math.sqrt(5);
        java.util.List<int[]> pts = new java.util.ArrayList<>();
        double cx = sx, cy = sy, vx = 0, vy = 0, wx = 0, wy = 0;
        int lastX = (int) Math.round(cx), lastY = (int) Math.round(cy), guard = 0;
        double dist;
        while ((dist = Math.hypot(dx - cx, dy - cy)) >= 1 && guard++ < 10000) {
            double wMag = Math.min(W, dist);
            if (dist >= D) {
                wx = wx / sqrt3 + (2 * rnd() - 1) * wMag / sqrt5;
                wy = wy / sqrt3 + (2 * rnd() - 1) * wMag / sqrt5;
            } else {
                wx /= sqrt3; wy /= sqrt3;
                if (M < 3) M = rnd() * 3 + 3; else M /= sqrt5;
            }
            vx += wx + G * (dx - cx) / dist;
            vy += wy + G * (dy - cy) / dist;
            double vMag = Math.hypot(vx, vy);
            if (vMag > M) {
                double vClip = M / 2 + rnd() * M / 2;
                vx = (vx / vMag) * vClip; vy = (vy / vMag) * vClip;
            }
            cx += vx; cy += vy;
            int mx = (int) Math.round(cx), my = (int) Math.round(cy);
            if (mx != lastX || my != lastY) { pts.add(new int[]{mx, my}); lastX = mx; lastY = my; }
        }
        pts.add(new int[]{(int) Math.round(dx), (int) Math.round(dy)});
        return pts;
    }

    static void humanMove(int tx, int ty) throws Exception {
        final Canvas c = findCanvas();
        if (c == null) throw new IllegalStateException("no canvas");
        int w = c.getWidth(), h = c.getHeight();
        for (int[] p : windMouse(curX, curY, tx, ty)) {
            final int px = clampi(p[0], 0, w - 1), py = clampi(p[1], 0, h - 1);
            SwingUtilities.invokeLater(() -> dispatchMove(c, px, py));
            Thread.sleep(1 + RNG.nextInt(7));            // pacing between motion samples
        }
        curX = tx; curY = ty;
    }
    static void dispatchMove(Canvas c, int x, int y) {
        c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_MOVED, System.currentTimeMillis(), 0, x, y, 0, false));
    }

    // human click: jittered endpoint, curved approach, reaction beat, press dwell
    static void humanClick(int x, int y) throws Exception {
        int jx = (int) Math.round(x + RNG.nextGaussian() * 2.2);   // land slightly off exact centre
        int jy = (int) Math.round(y + RNG.nextGaussian() * 2.2);
        humanMove(jx, jy);
        final Canvas c = findCanvas();
        final int fx = clampi(jx, 0, c.getWidth() - 1), fy = clampi(jy, 0, c.getHeight() - 1);
        Thread.sleep(50 + RNG.nextInt(160));             // reaction beat before pressing
        onEdt(() -> {
            long t = System.currentTimeMillis();
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_PRESSED, t, InputEvent.BUTTON1_DOWN_MASK, fx, fy, 1, false, MouseEvent.BUTTON1));
        });
        Thread.sleep(40 + RNG.nextInt(70));              // press dwell
        onEdt(() -> {
            long t = System.currentTimeMillis();
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_RELEASED, t, InputEvent.BUTTON1_DOWN_MASK, fx, fy, 1, false, MouseEvent.BUTTON1));
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_CLICKED, t, InputEvent.BUTTON1_DOWN_MASK, fx, fy, 1, false, MouseEvent.BUTTON1));
        });
    }
}
