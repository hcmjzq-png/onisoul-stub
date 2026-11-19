// Inspect IL metadata without executing any code from the inspected assembly.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Mono.Cecil;

public static class DumpLegacyUnityLayout
{
    private static readonly HashSet<string> Roots = new HashSet<string> {
        "System.Object", "System.ValueType", "UnityEngine.Object", "UnityEngine.Component",
        "UnityEngine.Behaviour", "UnityEngine.MonoBehaviour", "UnityEngine.ScriptableObject"
    };
    private static readonly HashSet<string> Vectors = new HashSet<string> {
        "UnityEngine.Vector2", "UnityEngine.Vector3", "UnityEngine.Vector4", "UnityEngine.Quaternion",
        "UnityEngine.Color", "UnityEngine.Color32", "UnityEngine.Rect", "UnityEngine.LayerMask"
    };
    private static readonly Dictionary<string, string> Scalars = new Dictionary<string, string> {
        { "System.Boolean", "bool" }, { "System.Int32", "int" }, { "System.UInt32", "uint" },
        { "System.Single", "float" }, { "System.String", "string" },
        { "System.Byte", "byte" }, { "System.SByte", "sbyte" },
        { "System.Int16", "short" }, { "System.UInt16", "ushort" }
    };
    private static string Name(TypeReference type) { return type.FullName.Replace('/', '+'); }

    private static string Describe(TypeReference type, IDictionary<string, string[][]> result)
    {
        string name = Name(type), scalar;
        if (Scalars.TryGetValue(name, out scalar)) return scalar;
        if (Vectors.Contains(name)) return "unity:" + name;
        var array = type as ArrayType;
        if (array != null && array.IsVector)
        {
            string element = Describe(array.ElementType, result);
            return element == null ? null : "array:" + element;
        }
        var generic = type as GenericInstanceType;
        if (generic != null && generic.ElementType.FullName == "System.Collections.Generic.List" + (char)96 + "1")
        {
            string element = Describe(generic.GenericArguments[0], result);
            return element == null ? null : "array:" + element;
        }
        if (type.Scope == null || type.Scope.Name == "mscorlib" || type.IsGenericInstance ||
            type.IsArray || type.IsByReference || type.IsPointer) return null;
        var definition = type.Resolve();
        if (definition.IsEnum) return "int";
        for (var parent = definition; parent != null && parent.FullName != "System.Object";)
        {
            if (parent.FullName == "UnityEngine.Object") return "ptr:" + type.Name;
            parent = parent.BaseType == null ? null : parent.BaseType.Resolve();
        }
        if (!definition.IsSerializable) return null;
        Gather(definition, result);
        return "object:" + name;
    }

    private static void Gather(TypeDefinition type, IDictionary<string, string[][]> result)
    {
        string name = Name(type);
        if (result.ContainsKey(name)) return;
        result.Add(name, null);
        var fields = new List<string[]>();
        if (type.BaseType != null && !Roots.Contains(type.BaseType.FullName))
        {
            var parent = type.BaseType.Resolve();
            Gather(parent, result);
            fields.AddRange(result[Name(parent)]);
        }
        foreach (var field in type.Fields)
        {
            if (field.IsStatic || field.IsInitOnly || field.IsNotSerialized ||
                (!field.IsPublic && !field.CustomAttributes.Any(a => a.AttributeType.FullName == "UnityEngine.SerializeField")))
                continue;
            string kind = Describe(field.FieldType, result);
            if (kind != null) fields.Add(new[] { field.Name, kind });
        }
        result[name] = fields.ToArray();
    }

    public static Dictionary<string, string[][]> Read(string directory, string[] requested, string fallbackDirectory)
    {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(directory);
        resolver.AddSearchDirectory(fallbackDirectory);
        var parameters = new ReaderParameters { AssemblyResolver = resolver };
        var types = new Dictionary<string, TypeDefinition>();
        foreach (string file in new[] {"Assembly-CSharp.dll", "Assembly-CSharp-firstpass.dll", "PlayMaker.dll"})
        {
            var assembly = AssemblyDefinition.ReadAssembly(Path.Combine(directory, file), parameters);
            foreach (var type in assembly.MainModule.Types)
                types[Name(type)] = type;
        }
        var result = new Dictionary<string, string[][]>();
        foreach (string name in requested) Gather(types[name], result);
        return result;
    }
}
