package com.portablevault.vault;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentResolver;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.text.method.ScrollingMovementMethod;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;

/**
 * Portable Privacy Vault - Android companion app.
 *
 * Uses the Storage Access Framework to locate the USB vault, then hands the
 * preconfigured Debian image to Termux, where QEMU boots it with the vault's
 * SharedData folder shared as /home/vault over virtio-9p.
 *
 * Requirements on the device:
 *   - Termux (from F-Droid)
 *   - in Termux:  pkg install qemu-system-x86_64
 *   - Termux setting "allow-external-apps = true"
 *   - grant this app the com.termux.permission.RUN_COMMAND permission
 */
public class MainActivity extends Activity {

    private static final int REQ_PICK_DIR = 1001;
    private static final String PREFS = "vault";
    private static final String KEY_TREE = "tree_uri";

    private static final String LAUNCH_SCRIPT =
        "set -u\n" +
        "echo 'Portable Privacy Vault - Android / Termux'\n" +
        "VAULT=''\n" +
        "for c in \"$@\"; do\n" +
        "  c=\"${c%/}\"\n" +
        "  if [ -f \"$c/Vault/system.img\" ]; then VAULT=\"$c\"; break; fi\n" +
        "  if [ -f \"$c/system.img\" ]; then VAULT=\"$(dirname \"$c\")\"; break; fi\n" +
        "done\n" +
        "if [ -z \"$VAULT\" ]; then\n" +
        "  echo 'Could not find Vault/system.img in the selected location.'\n" +
        "  echo 'Tried:'\n" +
        "  for c in \"$@\"; do echo \"  $c\"; done\n" +
        "  echo\n" +
        "  echo 'Android scoped storage often blocks USB-OTG paths. Workaround:'\n" +
        "  echo '  1. Copy the whole Vault folder to /sdcard/ (shared storage).'\n" +
        "  echo '  2. Re-select the vault here; /sdcard paths are retried.'\n" +
        "  exit 1\n" +
        "fi\n" +
        "IMG=\"$VAULT/Vault/system.img\"\n" +
        "SHARED=\"$VAULT/Vault/SharedData\"\n" +
        "echo \"Vault:  $VAULT\"\n" +
        "echo \"Image:  $IMG\"\n" +
        "echo \"Shared: $SHARED\"\n" +
        "if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then\n" +
        "  echo\n" +
        "  echo 'QEMU is not installed in Termux.'\n" +
        "  echo 'Run: pkg update && pkg install qemu-system-x86_64'\n" +
        "  exit 1\n" +
        "fi\n" +
        "test -f \"$IMG\" || { echo 'Missing system.img'; exit 1; }\n" +
        "test -d \"$SHARED\" || { echo 'Missing SharedData'; exit 1; }\n" +
        "echo 'Starting QEMU (TCG). Debian auto-logs in as user: vault'\n" +
        "echo 'Press Ctrl+C to stop the VM.'\n" +
        "qemu-system-x86_64 \\\n" +
        "  -name 'Portable Privacy Vault' \\\n" +
        "  -machine q35,accel=tcg -cpu max -m 1024 -smp 2 \\\n" +
        "  -drive \"file=$IMG,if=none,id=vaultdisk,format=qcow2\" \\\n" +
        "  -device virtio-blk-pci,drive=vaultdisk,bootindex=1 \\\n" +
        "  -snapshot \\\n" +
        "  -virtfs \"local,path=$SHARED,mount_tag=vault,security_model=none,multidevs=remap\" \\\n" +
        "  -device virtio-rng-pci -nographic -boot order=c\n" +
        "rc=$?\n" +
        "if [ $rc -ne 0 ]; then\n" +
        "  echo\n" +
        "  echo \"QEMU exited with status $rc.\"\n" +
        "  echo 'If it rejected -virtfs, this Termux QEMU build lacks 9p support.'\n" +
        "fi\n" +
        "exit $rc\n";

    private TextView status;
    private TextView contents;
    private Uri treeUri;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(36, 36, 36, 36);

        TextView title = new TextView(this);
        title.setText("Portable Privacy Vault");
        title.setTextSize(22);
        title.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView sub = new TextView(this);
        sub.setText("Pick the USB vault, then launch the sandboxed Debian VM in Termux.");
        sub.setPadding(0, 8, 0, 24);

        Button pick = new Button(this);
        pick.setText("Select vault USB folder");
        pick.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { pickFolder(); }
        });

        Button launch = new Button(this);
        launch.setText("Launch VM in Termux");
        launch.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { launchVm(); }
        });

        Button showContents = new Button(this);
        showContents.setText("List SharedData contents");
        showContents.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { listSharedData(); }
        });

        Button showConfig = new Button(this);
        showConfig.setText("Show vault config.json");
        showConfig.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showConfig(); }
        });

        Button help = new Button(this);
        help.setText("Termux setup help");
        help.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showTermuxHelp(); }
        });

        status = new TextView(this);
        status.setPadding(0, 16, 0, 16);

        contents = new TextView(this);
        contents.setTextSize(13);
        contents.setTextIsSelectable(true);
        contents.setMovementMethod(new ScrollingMovementMethod());
        contents.setBackgroundColor(Color.parseColor("#F0F0F0"));
        contents.setPadding(24, 24, 24, 24);
        contents.setText("No folder selected yet.");

        ScrollView scroll = new ScrollView(this);
        scroll.addView(contents, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        root.addView(title);
        root.addView(sub);
        root.addView(pick);
        root.addView(launch);
        root.addView(showContents);
        root.addView(showConfig);
        root.addView(help);
        root.addView(status);
        root.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        setContentView(root);

        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String saved = prefs.getString(KEY_TREE, null);
        if (saved != null) {
            treeUri = Uri.parse(saved);
            status.setText("Using saved vault folder.");
            listSharedData();
        } else {
            status.setText("Select the USB drive, then the Vault folder.");
        }
    }

    private void pickFolder() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        try {
            startActivityForResult(intent, REQ_PICK_DIR);
        } catch (Exception e) {
            toast("No file picker available: " + e.getMessage());
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_PICK_DIR || resultCode != RESULT_OK || data == null) {
            return;
        }
        Uri uri = data.getData();
        if (uri == null) {
            return;
        }
        final int flags = data.getFlags()
                & (Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try {
            getContentResolver().takePersistableUriPermission(uri, flags);
        } catch (SecurityException ignored) {
            // Some providers do not grant persistable permission.
        }
        treeUri = uri;
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                .putString(KEY_TREE, uri.toString()).apply();
        status.setText("Vault folder selected:\n" + uri);
        listSharedData();
    }

    // ---- SAF helpers -----------------------------------------------------

    private List<String[]> listChildren(String parentDocId) {
        List<String[]> out = new ArrayList<>();
        ContentResolver cr = getContentResolver();
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, parentDocId);
        Cursor c = null;
        try {
            c = cr.query(children, new String[]{
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                    DocumentsContract.Document.COLUMN_MIME_TYPE,
                    DocumentsContract.Document.COLUMN_SIZE
            }, null, null, null);
            if (c != null) {
                while (c.moveToNext()) {
                    out.add(new String[]{c.getString(0), c.getString(1), c.getString(2),
                            c.isNull(3) ? "" : c.getString(3)});
                }
            }
        } catch (Exception e) {
            toast("List failed: " + e.getMessage());
        } finally {
            if (c != null) c.close();
        }
        return out;
    }

    private String findChildDocId(String parentDocId, String name) {
        for (String[] row : listChildren(parentDocId)) {
            if (name.equalsIgnoreCase(row[1])
                    && DocumentsContract.Document.MIME_TYPE_DIR.equals(row[2])) {
                return row[0];
            }
        }
        return null;
    }

    private String treeRootId() {
        try {
            return DocumentsContract.getTreeDocumentId(treeUri);
        } catch (Exception e) {
            return null;
        }
    }

    /** Return the document id of <vault>/Vault, accepting a root or Vault selection. */
    private String resolveVaultDirId() {
        String rootId = treeRootId();
        if (rootId == null) {
            return null;
        }
        if (rootId.endsWith(":Vault") || rootId.endsWith("/Vault")) {
            return rootId;
        }
        String vaultId = findChildDocId(rootId, "Vault");
        if (vaultId != null) {
            return vaultId;
        }
        if (findChildDocId(rootId, "SharedData") != null) {
            return rootId;
        }
        return null;
    }

    private String resolveSharedData() {
        if (treeUri == null) {
            status.setText("Select the vault USB folder first.");
            return null;
        }
        String vaultId = resolveVaultDirId();
        if (vaultId == null) {
            return null;
        }
        return findChildDocId(vaultId, "SharedData");
    }

    private void listSharedData() {
        String sharedId = resolveSharedData();
        if (sharedId == null) {
            contents.setText("Could not find Vault/SharedData in the selected folder.\n\n"
                    + "Pick the drive root that contains the 'Vault' folder.");
            return;
        }
        List<String[]> rows = listChildren(sharedId);
        StringBuilder sb = new StringBuilder();
        sb.append("Vault/SharedData (").append(rows.size()).append(" entries)\n\n");
        for (String[] row : rows) {
            boolean dir = DocumentsContract.Document.MIME_TYPE_DIR.equals(row[2]);
            sb.append(dir ? "[DIR]  " : "[FILE] ");
            sb.append(row[1]);
            if (!dir && row[3] != null && row[3].length() > 0) {
                try {
                    long size = Long.parseLong(row[3]);
                    sb.append("  (").append(size).append(" bytes)");
                } catch (NumberFormatException ignored) { }
            }
            sb.append("\n");
        }
        contents.setText(sb.toString());
        status.setText("Loaded SharedData from the USB vault.");
    }

    private void showConfig() {
        String vaultId = resolveVaultDirId();
        if (vaultId == null) {
            status.setText("Select the vault USB folder first.");
            return;
        }
        String configId = findChildDocId(vaultId, "config.json");
        if (configId == null) {
            contents.setText("config.json not found in Vault/.");
            return;
        }
        Uri doc = DocumentsContract.buildDocumentUriUsingTree(treeUri, configId);
        StringBuilder sb = new StringBuilder();
        InputStream in = null;
        BufferedReader reader = null;
        try {
            in = getContentResolver().openInputStream(doc);
            if (in != null) {
                reader = new BufferedReader(new InputStreamReader(in, "UTF-8"));
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line).append('\n');
                }
            }
        } catch (Exception e) {
            sb.append("Read error: ").append(e.getMessage());
        } finally {
            try { if (reader != null) reader.close(); } catch (Exception ignored) { }
            try { if (in != null) in.close(); } catch (Exception ignored) { }
        }
        contents.setText(sb.length() == 0 ? "(empty config)" : sb.toString());
        status.setText("Showing Vault/config.json");
    }

    // ---- Termux handoff --------------------------------------------------

    private List<String> candidatePaths() {
        List<String> out = new ArrayList<>();
        String rootId = treeRootId();
        if (rootId == null) {
            return out;
        }
        int colon = rootId.indexOf(':');
        String volume = colon >= 0 ? rootId.substring(0, colon) : "primary";
        String rel = colon >= 0 ? rootId.substring(colon + 1) : rootId;
        while (rel.startsWith("/")) {
            rel = rel.substring(1);
        }

        List<String> bases = new ArrayList<>();
        if ("primary".equals(volume) || "home".equals(volume)) {
            bases.add("/storage/emulated/0");
            bases.add("/sdcard");
        } else {
            bases.add("/storage/" + volume);
            bases.add("/mnt/media_rw/" + volume);
            bases.add("/storage/emulated/0");
            bases.add("/sdcard");
        }
        for (String base : bases) {
            out.add(rel.isEmpty() ? base : base + "/" + rel);
        }
        return out;
    }

    private void launchVm() {
        if (treeUri == null) {
            status.setText("Select the vault USB folder first.");
            toast("Pick the USB vault folder first.");
            return;
        }
        List<String> candidates = candidatePaths();
        if (candidates.isEmpty()) {
            toast("Could not derive a filesystem path from the selection.");
            return;
        }

        String[] arguments = new String[2 + candidates.size()];
        arguments[0] = "-c";
        arguments[1] = LAUNCH_SCRIPT;
        arguments[2] = "vault";
        for (int i = 0; i < candidates.size(); i++) {
            arguments[3 + i] = candidates.get(i);
        }

        Intent i = new Intent("com.termux.RUN_COMMAND");
        i.setClassName("com.termux", "com.termux.app.RunCommandService");
        i.putExtra("com.termux.RUN_COMMAND_PATH",
                "/data/data/com.termux/files/usr/bin/bash");
        i.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", arguments);
        i.putExtra("com.termux.RUN_COMMAND_WORKDIR",
                "/data/data/com.termux/files/home");
        i.putExtra("com.termux.RUN_COMMAND_BACKGROUND", false);
        try {
            startService(i);
            status.setText("Handed off to Termux. The Debian console opens there.");
            contents.setText("Termux launch requested.\n\nCandidate paths:\n  "
                    + String.join("\n  ", candidates)
                    + "\n\nIf Termux cannot find the vault, see the Termux setup help.");
        } catch (Exception e) {
            status.setText("Could not start Termux.");
            showTermuxHelp();
        }
    }

    private void showTermuxHelp() {
        String message =
                "Install Termux from F-Droid (not the Play Store).\n\n" +
                "In Termux run:\n" +
                "  pkg update\n" +
                "  pkg install qemu-system-x86_64\n\n" +
                "Enable external commands:\n" +
                "  echo 'allow-external-apps = true' >> ~/.termux/termux.properties\n" +
                "  termux-reload-settings\n\n" +
                "Grant this app the RUN_COMMAND permission (Android settings > Apps > " +
                "Vault Runner > Permissions), then press 'Launch VM in Termux' again.\n\n" +
                "USB-OTG access: Android often blocks direct USB paths for apps. " +
                "If Termux cannot see /storage/XXXX-XXXX, copy the Vault folder to " +
                "/sdcard/Vault and select it there.";
        new AlertDialog.Builder(this)
                .setTitle("Termux + QEMU setup")
                .setMessage(message)
                .setPositiveButton("OK", null)
                .show();
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }
}
