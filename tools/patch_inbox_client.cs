using System;
using System.IO;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

public static class PatchInboxClient
{
    public static void Run(string input, string output, string references)
    {
        using (var resolver = new DefaultAssemblyResolver())
        {
            resolver.AddSearchDirectory(Path.GetDirectoryName(input));
            resolver.AddSearchDirectory(references);
            Patch(input, output, resolver);
        }
    }

    private static void Patch(string input, string output, IAssemblyResolver resolver)
    {
        using (var module = ModuleDefinition.ReadModule(input,
                    new ReaderParameters { InMemory = true, AssemblyResolver = resolver }))
        {
            var reader = module.GetType("InboxReader");
            var resolve = reader.Methods.Single(m => m.Name == "resolve");
            var convert = reader.Methods.Single(m => m.Name == "convertHtmlParameter");
            var isResolving = reader.Methods.Single(m => m.Name == "get_IsOpenInboxReader");

            // Reuse the existing compiler-generated worker callback and legacy delegate types.
            var resolveCode = resolve.Body.Instructions;
            var closureConstructor = (MethodReference)resolveCode.First().Operand;
            var closure = closureConstructor.DeclaringType.Resolve();
            var completion = closure.Methods.Single(m => !m.IsConstructor);
            var completionField = closure.Fields.Single(f => f.Name == "endCallback");
            var endCallbackConstructor = FindCall(resolve, "BrowserProxy/EndCallback::.ctor(", Code.Newobj);
            var worker = FindCall(resolve, "::get_Instance()", Code.Call);
            var runWorker = FindCall(resolve, "InboxResolveWorker::resolve(", Code.Callvirt);
            var respond = FindCall(resolve, "BrowserProxy/Callback::Invoke(", Code.Callvirt);
            var tableConstructor = convert.Body.Instructions
                .Where(i => i.OpCode == OpCodes.Newobj)
                .Select(i => (MethodReference)i.Operand)
                .First(m => m.DeclaringType.FullName == "System.Collections.Hashtable" && !m.HasParameters);
            var tableSet = convert.Body.Instructions
                .Select(i => i.Operand as MethodReference)
                .First(m => m != null && m.Name == "set_Item" &&
                            m.DeclaringType.FullName == "System.Collections.Hashtable");
            if (completionField.FieldType.FullName != "BrowserProxy/EndCallback" ||
                resolve.Parameters.Count != 2 || resolve.Parameters[1].ParameterType.FullName != "BrowserProxy/Callback" ||
                convert.Body.Instructions.Any(i => (i.Operand as string) == "inboxKeepOpen"))
                throw new InvalidDataException("Unexpected InboxReader compatibility baseline");

            completionField.Name = "reply";
            completionField.FieldType = resolve.Parameters[1].ParameterType;
            completion.Body = new MethodBody(completion);
            var done = completion.Body.GetILProcessor();
            done.Emit(OpCodes.Ldarg_0);
            done.Emit(OpCodes.Ldfld, completionField);
            done.Emit(OpCodes.Ldnull);
            done.Emit(OpCodes.Callvirt, respond);
            done.Emit(OpCodes.Ret);

            resolve.Body = new MethodBody(resolve) { InitLocals = true };
            var callback = new VariableDefinition(closure);
            var busy = new VariableDefinition(tableConstructor.DeclaringType);
            resolve.Body.Variables.Add(callback);
            resolve.Body.Variables.Add(busy);
            var il = resolve.Body.GetILProcessor();
            var start = il.Create(OpCodes.Newobj, closureConstructor);
            il.Emit(OpCodes.Call, isResolving);
            il.Emit(OpCodes.Brfalse, start);
            il.Emit(OpCodes.Newobj, tableConstructor);
            il.Emit(OpCodes.Stloc, busy);
            il.Emit(OpCodes.Ldloc, busy);
            il.Emit(OpCodes.Ldstr, "busy");
            il.Emit(OpCodes.Ldc_I4_1);
            il.Emit(OpCodes.Box, module.TypeSystem.Boolean);
            il.Emit(OpCodes.Callvirt, tableSet);
            il.Emit(OpCodes.Ldarg_2);
            il.Emit(OpCodes.Ldloc, busy);
            il.Emit(OpCodes.Callvirt, respond);
            il.Emit(OpCodes.Ret);

            il.Append(start);
            il.Emit(OpCodes.Stloc, callback);
            il.Emit(OpCodes.Ldloc, callback);
            il.Emit(OpCodes.Ldarg_2);
            il.Emit(OpCodes.Stfld, completionField);
            il.Emit(OpCodes.Call, worker);
            il.Emit(OpCodes.Ldarg_1);
            il.Emit(OpCodes.Ldloc, callback);
            il.Emit(OpCodes.Ldftn, completion);
            il.Emit(OpCodes.Newobj, endCallbackConstructor);
            il.Emit(OpCodes.Callvirt, runWorker);
            il.Emit(OpCodes.Ret);

            var finalReturn = convert.Body.Instructions.Single(i => i.OpCode == OpCodes.Ret);
            var conversion = convert.Body.GetILProcessor();
            foreach (var instruction in new[] {
                conversion.Create(OpCodes.Ldarg_1), conversion.Create(OpCodes.Ldind_Ref),
                conversion.Create(OpCodes.Ldstr, "inboxKeepOpen"), conversion.Create(OpCodes.Ldc_I4_1),
                conversion.Create(OpCodes.Box, module.TypeSystem.Boolean), conversion.Create(OpCodes.Callvirt, tableSet)
            })
                conversion.InsertBefore(finalReturn, instruction);
            module.Write(output);
        }
    }

    private static MethodReference FindCall(MethodDefinition method, string signature, Code opcode)
    {
        return method.Body.Instructions.Where(i => i.OpCode.Code == opcode)
            .Select(i => (MethodReference)i.Operand).Single(target => target.FullName.Contains(signature));
    }
}
