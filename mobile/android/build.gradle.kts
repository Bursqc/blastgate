allprojects {
    repositories {
        google()
        mavenCentral()
        maven { url = uri("https://jitpack.io") }  // Required for ESP BLE Prov
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

// Workaround for legacy Flutter plugins (e.g. flutter_esp_ble_prov 0.1.7) that
// still rely on package="..." in AndroidManifest.xml. AGP 8+ requires
// `namespace` in build.gradle instead; here we read the manifest's package
// attribute and inject it as the module's namespace at configure time.
subprojects {
    afterEvaluate {
        val androidExt = extensions.findByName("android") ?: return@afterEvaluate
        val getNs = androidExt.javaClass.methods.firstOrNull { it.name == "getNamespace" } ?: return@afterEvaluate
        val setNs = androidExt.javaClass.methods.firstOrNull { it.name == "setNamespace" } ?: return@afterEvaluate
        if (getNs.invoke(androidExt) == null) {
            val manifest = file("src/main/AndroidManifest.xml")
            if (manifest.exists()) {
                val regex = Regex("""package\s*=\s*"([^"]+)"""")
                val match = regex.find(manifest.readText())
                if (match != null) {
                    setNs.invoke(androidExt, match.groupValues[1])
                    logger.lifecycle("[namespace-fixup] ${project.name} -> ${match.groupValues[1]}")
                }
            }
        }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
