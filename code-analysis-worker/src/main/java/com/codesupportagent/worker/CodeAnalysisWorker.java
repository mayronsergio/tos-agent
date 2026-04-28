package com.codesupportagent.worker;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.Position;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.EnumDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.nodeTypes.NodeWithAnnotations;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.resolution.UnsolvedSymbolException;
import com.github.javaparser.resolution.declarations.ResolvedMethodDeclaration;
import com.github.javaparser.resolution.types.ResolvedType;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Stream;

public class CodeAnalysisWorker {
    public static void main(String[] args) throws Exception {
        Map<String, String> options = Args.parse(args);
        Path source = Path.of(required(options, "source")).toAbsolutePath().normalize();
        Path root = Path.of(options.getOrDefault("root", source.toString())).toAbsolutePath().normalize();
        Path output = Path.of(required(options, "output")).toAbsolutePath().normalize();
        Context context = new Context(
                options.getOrDefault("artifactId", ""),
                options.getOrDefault("version", ""),
                options.getOrDefault("sourceType", "sources")
        );

        AnalysisResult result = new Analyzer(source, root, context).analyze();
        Gson gson = new GsonBuilder().disableHtmlEscaping().setPrettyPrinting().create();
        Files.createDirectories(output.getParent());
        Files.writeString(output, gson.toJson(result), StandardCharsets.UTF_8);
    }

    private static String required(Map<String, String> options, String key) {
        String value = options.get(key);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Missing --" + key);
        }
        return value;
    }

    static final class Analyzer {
        private final Path source;
        private final Path root;
        private final Context context;
        private final JavaParser parser;
        private final AnalysisResult result = new AnalysisResult();

        Analyzer(Path source, Path root, Context context) {
            this.source = source;
            this.root = root;
            this.context = context;
            CombinedTypeSolver typeSolver = new CombinedTypeSolver();
            typeSolver.add(new ReflectionTypeSolver(false));
            if (Files.isDirectory(source)) {
                typeSolver.add(new JavaParserTypeSolver(source));
            }
            ParserConfiguration configuration = new ParserConfiguration()
                    .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17)
                    .setSymbolResolver(new JavaSymbolSolver(typeSolver));
            this.parser = new JavaParser(configuration);
        }

        AnalysisResult analyze() throws IOException {
            int javaFiles = 0;
            try (Stream<Path> files = Files.walk(source)) {
                List<Path> javaSources = files.filter(path -> path.toString().endsWith(".java")).toList();
                javaFiles = javaSources.size();
                for (Path file : javaSources) {
                    analyzeFile(file);
                }
            }
            long resolvedCalls = result.relations.stream()
                    .filter(relation -> relation.type.equals("METHOD_CALLS_METHOD") && relation.reason.equals("JavaSymbolSolver"))
                    .count();
            long unresolvedCalls = result.relations.stream()
                    .filter(relation -> relation.type.equals("METHOD_CALLS_METHOD") && relation.reason.startsWith("fallback"))
                    .count();
            result.metrics.put("javaFilesAnalyzed", javaFiles);
            result.metrics.put("relationsGenerated", result.relations.size());
            result.metrics.put("resolvedMethodCalls", (int) resolvedCalls);
            result.metrics.put("unresolvedMethodCalls", (int) unresolvedCalls);
            return result;
        }

        private void analyzeFile(Path file) {
            try {
                Optional<CompilationUnit> parsed = parser.parse(file).getResult();
                if (parsed.isEmpty()) {
                    return;
                }
                CompilationUnit cu = parsed.get();
                String packageName = cu.getPackageDeclaration().map(pkg -> pkg.getNameAsString()).orElse("");
                String relPath = relative(file);
                for (TypeDeclaration<?> type : cu.getTypes()) {
                    analyzeType(cu, type, relPath, packageName);
                }
            } catch (Exception ignored) {
                // Keep the worker best-effort. Python fallback covers complete failure.
            }
        }

        private void analyzeType(CompilationUnit cu, TypeDeclaration<?> type, String relPath, String packageName) {
            String className = type.getNameAsString();
            String symbolType = type instanceof EnumDeclaration ? "enum" : type instanceof ClassOrInterfaceDeclaration coi && coi.isInterface() ? "interface" : "class";
            List<String> annotations = annotations(type);
            List<String> imports = cu.getImports().stream().map(importDeclaration -> importDeclaration.getNameAsString()).toList();
            String layer = detectLayer(className, annotations, relPath);
            String tableName = tableName(type);
            String entityName = annotations.stream().anyMatch(name -> name.equals("Entity") || name.equals("Table")) ? className : null;
            List<String> methods = type.getMethods().stream().map(MethodDeclaration::getNameAsString).toList();
            List<String> constructors = type.getConstructors().stream().map(ConstructorDeclaration::getDeclarationAsString).toList();
            List<String> fields = fieldNames(type);
            List<String> constants = constants(type);
            String superclass = null;
            String genericSuperclass = null;
            List<String> genericArguments = new ArrayList<>();
            List<String> interfaces = new ArrayList<>();

            if (type instanceof ClassOrInterfaceDeclaration coi) {
                if (!coi.getExtendedTypes().isEmpty()) {
                    ClassOrInterfaceType ext = coi.getExtendedTypes(0);
                    superclass = rawType(ext);
                    genericSuperclass = ext.toString().contains("<") ? ext.toString() : null;
                    genericArguments.addAll(genericArguments(ext));
                    result.relations.add(new RelationJson("CLASS_EXTENDS_CLASS", className, superclass, relPath, null, "extends resolvido via AST"));
                }
                for (ClassOrInterfaceType impl : coi.getImplementedTypes()) {
                    interfaces.add(rawType(impl));
                    result.relations.add(new RelationJson("CLASS_IMPLEMENTS_INTERFACE", className, rawType(impl), relPath, null, "implements resolvido via AST"));
                }
            }

            SymbolJson classSymbol = SymbolJson.base(context, relPath, Path.of(relPath).getFileName().toString(), symbolType, className);
            classSymbol.packageName = packageName;
            classSymbol.className = symbolType.equals("class") ? className : null;
            classSymbol.enumName = symbolType.equals("enum") ? className : null;
            classSymbol.interfaceName = symbolType.equals("interface") ? className : null;
            classSymbol.superclass = superclass;
            classSymbol.genericSuperclass = genericSuperclass;
            classSymbol.genericArguments = genericArguments;
            classSymbol.interfaces = interfaces;
            classSymbol.annotations = annotations;
            classSymbol.methods = methods;
            classSymbol.constructors = constructors;
            classSymbol.imports = imports;
            classSymbol.fields = fields;
            classSymbol.constants = constants;
            classSymbol.overriddenMethods = overriddenMethods(type);
            classSymbol.tableName = tableName;
            classSymbol.entityName = entityName;
            classSymbol.layer = layer;
            classSymbol.snippet = snippet(type);
            classSymbol.lineStart = beginLine(type);
            classSymbol.lineEnd = endLine(type);
            classSymbol.tags = tags(symbolType, layer, entityName);
            result.symbols.add(classSymbol);

            if (tableName != null) {
                result.relations.add(new RelationJson("ENTITY_MAPS_TABLE", className, tableName, relPath, null, "@Table ou query detectada"));
            }
            for (String annotation : annotations) {
                result.relations.add(new RelationJson("ANNOTATED_WITH", className, annotation, relPath, null, "annotation na classe"));
            }
            for (String argument : genericArguments) {
                result.relations.add(new RelationJson("CLASS_HAS_GENERIC_ARGUMENT", className, argument, relPath, null, "tipo parametrizado"));
            }

            analyzeFields(type, relPath, packageName, className, layer, entityName, superclass, genericSuperclass, genericArguments, interfaces, annotations);
            analyzeMethods(type, relPath, packageName, className, layer, entityName, superclass, genericSuperclass, genericArguments, interfaces, annotations);
        }

        private void analyzeFields(TypeDeclaration<?> type, String relPath, String packageName, String className, String layer, String entityName,
                                   String superclass, String genericSuperclass, List<String> genericArguments, List<String> interfaces, List<String> classAnnotations) {
            for (FieldDeclaration field : type.getFields()) {
                String fieldType = resolveType(field);
                for (var variable : field.getVariables()) {
                    SymbolJson symbol = SymbolJson.base(context, relPath, Path.of(relPath).getFileName().toString(), field.isStatic() && field.isFinal() ? "constant" : "field", variable.getNameAsString());
                    symbol.packageName = packageName;
                    symbol.className = className;
                    symbol.superclass = superclass;
                    symbol.genericSuperclass = genericSuperclass;
                    symbol.genericArguments = genericArguments;
                    symbol.interfaces = interfaces;
                    symbol.annotations = classAnnotations;
                    symbol.fieldType = fieldType;
                    symbol.fieldAnnotations = annotations(field);
                    symbol.entityName = entityName;
                    symbol.layer = layer;
                    symbol.snippet = snippet(field);
                    symbol.lineStart = beginLine(field);
                    symbol.lineEnd = endLine(field);
                    symbol.tags = tags(symbol.symbolType, layer, entityName);
                    result.symbols.add(symbol);
                    result.relations.add(new RelationJson("FIELD_HAS_TYPE", className, fieldType, relPath, null, "tipo de campo resolvido"));
                    for (String annotation : symbol.fieldAnnotations) {
                        result.relations.add(new RelationJson("ANNOTATED_WITH", className + "." + variable.getNameAsString(), annotation, relPath, null, "annotation no campo"));
                    }
                }
            }
        }

        private void analyzeMethods(TypeDeclaration<?> type, String relPath, String packageName, String className, String layer, String entityName,
                                    String superclass, String genericSuperclass, List<String> genericArguments, List<String> interfaces, List<String> classAnnotations) {
            for (MethodDeclaration method : type.getMethods()) {
                SymbolJson symbol = SymbolJson.base(context, relPath, Path.of(relPath).getFileName().toString(), "method", method.getNameAsString());
                symbol.packageName = packageName;
                symbol.className = className;
                symbol.methodName = method.getNameAsString();
                symbol.superclass = superclass;
                symbol.genericSuperclass = genericSuperclass;
                symbol.genericArguments = genericArguments;
                symbol.interfaces = interfaces;
                symbol.annotations = classAnnotations;
                symbol.overriddenMethods = method.isAnnotationPresent("Override") ? List.of(method.getNameAsString()) : List.of();
                symbol.entityName = entityName;
                symbol.layer = layer;
                symbol.signature = method.getDeclarationAsString(false, false, false);
                symbol.snippet = snippet(method);
                symbol.lineStart = beginLine(method);
                symbol.lineEnd = endLine(method);
                symbol.tags = tags("method", layer, entityName);
                result.symbols.add(symbol);
                result.relations.add(new RelationJson("METHOD_RETURNS_TYPE", className + "." + method.getNameAsString(), resolveType(method.getType()), relPath, method.getNameAsString(), "tipo de retorno resolvido"));
                method.getParameters().forEach(parameter -> result.relations.add(new RelationJson("METHOD_PARAM_TYPE", className + "." + method.getNameAsString(), resolveType(parameter.getType()), relPath, method.getNameAsString(), "tipo de parametro resolvido")));
                if (method.isAnnotationPresent("Override")) {
                    result.relations.add(new RelationJson("METHOD_OVERRIDES_METHOD", className, method.getNameAsString(), relPath, method.getNameAsString(), "@Override"));
                }
                method.findAll(MethodCallExpr.class).forEach(call -> addMethodCallRelation(className, method, call, relPath));
            }
        }

        private void addMethodCallRelation(String className, MethodDeclaration method, MethodCallExpr call, String relPath) {
            try {
                ResolvedMethodDeclaration resolved = call.resolve();
                String target = resolved.declaringType().getQualifiedName() + "." + resolved.getName();
                result.relations.add(new RelationJson("METHOD_CALLS_METHOD", className + "." + method.getNameAsString(), target, relPath, method.getNameAsString(), "JavaSymbolSolver"));
                result.relations.add(new RelationJson("CLASS_USES_CLASS", className, resolved.declaringType().getQualifiedName(), relPath, method.getNameAsString(), "classe dona do metodo chamado"));
            } catch (UnsolvedSymbolException | UnsupportedOperationException | IllegalStateException ignored) {
                result.relations.add(new RelationJson("METHOD_CALLS_METHOD", className + "." + method.getNameAsString(), call.getNameAsString(), relPath, method.getNameAsString(), "fallback AST method call"));
            }
        }

        private String resolveType(com.github.javaparser.ast.type.Type type) {
            try {
                ResolvedType resolved = type.resolve();
                return resolved.describe();
            } catch (Exception ignored) {
                return type.asString();
            }
        }

        private String resolveType(FieldDeclaration field) {
            if (field.getVariables().isEmpty()) {
                return field.getElementType().asString();
            }
            return resolveType(field.getElementType());
        }

        private List<String> fieldNames(TypeDeclaration<?> type) {
            return type.getFields().stream().flatMap(field -> field.getVariables().stream()).map(variable -> variable.getNameAsString()).toList();
        }

        private List<String> constants(TypeDeclaration<?> type) {
            return type.getFields().stream()
                    .filter(field -> field.isStatic() && field.isFinal())
                    .flatMap(field -> field.getVariables().stream())
                    .map(variable -> variable.getNameAsString())
                    .toList();
        }

        private List<String> overriddenMethods(TypeDeclaration<?> type) {
            return type.getMethods().stream().filter(method -> method.isAnnotationPresent("Override")).map(MethodDeclaration::getNameAsString).toList();
        }

        private List<String> annotations(NodeWithAnnotations<?> node) {
            return node.getAnnotations().stream().map(AnnotationExpr::getNameAsString).toList();
        }

        private String tableName(TypeDeclaration<?> type) {
            for (AnnotationExpr annotation : type.getAnnotations()) {
                if (annotation.getNameAsString().equals("Table")) {
                    String text = annotation.toString();
                    java.util.regex.Matcher matcher = java.util.regex.Pattern.compile("name\\s*=\\s*\"([^\"]+)\"").matcher(text);
                    if (matcher.find()) {
                        return matcher.group(1);
                    }
                }
            }
            return null;
        }

        private String detectLayer(String className, List<String> annotations, String relPath) {
            String text = (className + " " + relPath + " " + String.join(" ", annotations)).toLowerCase();
            if (text.contains("controller") || text.contains("restcontroller") || text.contains("action")) return "controller/action";
            if (text.contains("service")) return "service";
            if (text.contains("activity")) return "activity";
            if (text.contains("repository") || text.contains("dao")) return "dao/repository";
            if (text.contains("entity") || text.contains("model")) return "entity";
            if (text.contains("dto")) return "dto";
            if (text.contains("config")) return "config";
            if (text.contains("util")) return "util";
            return "unknown";
        }

        private String rawType(ClassOrInterfaceType type) {
            return type.getNameAsString();
        }

        private List<String> genericArguments(ClassOrInterfaceType type) {
            return type.getTypeArguments().map(args -> args.stream().map(Object::toString).map(this::rawName).toList()).orElse(List.of());
        }

        private String rawName(String value) {
            int index = value.indexOf('<');
            return index >= 0 ? value.substring(0, index).trim() : value.trim();
        }

        private List<String> tags(String symbolType, String layer, String entityName) {
            LinkedHashSet<String> tags = new LinkedHashSet<>();
            tags.add(symbolType);
            if (layer != null && !layer.isBlank()) tags.add(layer);
            if (entityName != null) tags.add("entity");
            return new ArrayList<>(tags);
        }

        private String snippet(Node node) {
            String value = node.toString();
            return value.length() > 4000 ? value.substring(0, 4000) : value;
        }

        private int beginLine(Node node) {
            return node.getBegin().map(position -> position.line).orElse(1);
        }

        private int endLine(Node node) {
            return node.getEnd().map(position -> position.line).orElse(beginLine(node));
        }

        private String relative(Path file) {
            try {
                return root.relativize(file.toAbsolutePath().normalize()).toString().replace('\\', '/');
            } catch (Exception ignored) {
                return source.relativize(file.toAbsolutePath().normalize()).toString().replace('\\', '/');
            }
        }
    }
}
