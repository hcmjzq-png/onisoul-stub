using System;
using System.IO;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

public static class PatchActionPointClient
{
    public static void Run(string input, string output, string references)
    {
        if (File.Exists(output)) throw new IOException("Refusing to overwrite assembly output");
        using (var resolver = new DefaultAssemblyResolver())
        {
            resolver.AddSearchDirectory(Path.GetDirectoryName(input));
            resolver.AddSearchDirectory(references);
            using var assembly = AssemblyDefinition.ReadAssembly(input, new ReaderParameters { AssemblyResolver = resolver });
            if (assembly.Name.HasPublicKey) throw new InvalidDataException("Signed assembly unsupported");
            var module = assembly.MainModule;
            var refresher = module.Types.Single(t => t.FullName == "ActionPointRefresher");
            var status = module.Types.Single(t => t.FullName == "UserStatus");
            var pointBox = status.NestedTypes.Single(t => t.Name == "ActionPoint");
            var current = pointBox.Fields.Single(f => f.Name == "point_");
            var cap = pointBox.Fields.Single(f => f.Name == "maxPoint_");
            var stamp = pointBox.Fields.Single(f => f.Name == "confirmTime_");
            var owner = refresher.Fields.Single(f => f.Name == "userStatus_");
            var key = refresher.Fields.Single(f => f.Name == "key_");
            var due = refresher.Fields.Single(f => f.Name == "refreshTime_");
            var interval = refresher.Fields.Single(f => f.Name == "recoverIntervalTime_");
            var lookup = status.Methods.Single(m => m.Name == "getActionPoint" && m.ReturnType == pointBox);
            var seconds = refresher.Methods.Single(m => m.Name == "get_Sec" && m.Parameters.Count == 0);
            var snapshot = refresher.Methods.Single(m => m.Name == "setActionPoint" && m.Parameters.Count == 2);
            var update = refresher.Methods.Single(m => m.Name == "update" && m.Parameters.Count == 0);
            if (!seconds.Body.Instructions.Any(i => i.OpCode == OpCodes.Mul) ||
                snapshot.Body.Instructions.Any(i => i.Operand == stamp))
                throw new InvalidDataException("Unexpected or already patched action point methods");

            var calls = seconds.Body.Instructions.Select(i => i.Operand).OfType<MethodReference>().ToArray();
            var clock = calls.Single(m => m.DeclaringType.FullName == "ServiceLocator`1<ClockTimer>" && m.Name == "get_Instance");
            var now = calls.Single(m => m.DeclaringType.FullName == "ClockTimer" && m.Name == "get_fSec");
            var maxCall = update.Body.Instructions.Single(i => i.Operand is MethodReference m &&
                m.DeclaringType.FullName == "System.Math" && m.Name == "Max" && m.ReturnType.MetadataType == MetadataType.Double);
            var math = (MethodReference)maxCall.Operand;
            var minDouble = MathMethod(math.DeclaringType, "Min", module.TypeSystem.Double, 2);
            var minInt = MathMethod(math.DeclaringType, "Min", module.TypeSystem.Int32, 2);
            var ceil = MathMethod(math.DeclaringType, "Ceiling", module.TypeSystem.Double, 1);

            // At cap show no countdown. Otherwise show the next tick in [0, interval].
            seconds.Body.Instructions.Clear();
            seconds.Body.Variables.Clear();
            var box = new VariableDefinition(pointBox);
            seconds.Body.Variables.Add(box);
            var display = seconds.Body.GetILProcessor();
            var active = Instruction.Create(OpCodes.Ldc_R8, 0.0);
            display.Emit(OpCodes.Ldarg_0);
            display.Emit(OpCodes.Ldfld, owner);
            display.Emit(OpCodes.Ldarg_0);
            display.Emit(OpCodes.Ldfld, key);
            display.Emit(OpCodes.Callvirt, lookup);
            display.Emit(OpCodes.Stloc, box);
            display.Emit(OpCodes.Ldloc, box);
            display.Emit(OpCodes.Ldfld, current);
            display.Emit(OpCodes.Ldloc, box);
            display.Emit(OpCodes.Ldfld, cap);
            display.Emit(OpCodes.Blt, active);
            display.Emit(OpCodes.Ldc_I4_0);
            display.Emit(OpCodes.Ret);
            display.Append(active);
            display.Emit(OpCodes.Ldarg_0);
            display.Emit(OpCodes.Ldfld, due);
            display.Emit(OpCodes.Call, clock);
            display.Emit(OpCodes.Callvirt, now);
            display.Emit(OpCodes.Sub);
            display.Emit(OpCodes.Call, math);
            display.Emit(OpCodes.Ldarg_0);
            display.Emit(OpCodes.Ldfld, interval);
            display.Emit(OpCodes.Conv_R8);
            display.Emit(OpCodes.Call, minDouble);
            display.Emit(OpCodes.Call, ceil);
            display.Emit(OpCodes.Conv_I4);
            display.Emit(OpCodes.Ret);

            // UserStatus.ActionPoint.update sets confirmTime before invoking the status view.
            var anchor = snapshot.Body.GetILProcessor();
            var fallback = snapshot.Body.Instructions[0];
            var last = new VariableDefinition(module.TypeSystem.Int64);
            snapshot.Body.Variables.Add(last);
            foreach (var instruction in new[] {
                Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Ldfld, owner),
                Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Ldfld, key),
                Instruction.Create(OpCodes.Callvirt, lookup), Instruction.Create(OpCodes.Ldfld, stamp),
                Instruction.Create(OpCodes.Stloc, last), Instruction.Create(OpCodes.Ldloc, last),
                Instruction.Create(OpCodes.Ldc_I8, 0L), Instruction.Create(OpCodes.Ble, fallback),
                Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Ldloc, last),
                Instruction.Create(OpCodes.Conv_R8), Instruction.Create(OpCodes.Ldarg_0),
                Instruction.Create(OpCodes.Ldfld, interval), Instruction.Create(OpCodes.Conv_R8),
                Instruction.Create(OpCodes.Add), Instruction.Create(OpCodes.Stfld, due),
                Instruction.Create(OpCodes.Ret),
            }) anchor.InsertBefore(fallback, instruction);

            // The due tick itself counts, and subsequent ticks keep the same phase.
            var increment = maxCall.Previous;
            var store = maxCall.Next.Next;
            var saveDue = update.Body.Instructions.Last(i => i.OpCode == OpCodes.Stfld && i.Operand == due);
            var add = saveDue.Previous;
            var loadNow = add.Previous.Previous.Previous.Previous;
            var updatedBox = update.Body.Variables[0];
            if (increment.OpCode != OpCodes.Ldc_R8 || (double)increment.Operand != 1.0 ||
                increment.Previous.OpCode != OpCodes.Div || maxCall.Next.OpCode != OpCodes.Conv_I4 ||
                store.OpCode != OpCodes.Stloc_S || !(store.Operand is VariableDefinition count) ||
                add.OpCode != OpCodes.Add || loadNow.OpCode != OpCodes.Ldloc_2 ||
                updatedBox.VariableType.FullName != pointBox.FullName)
                throw new InvalidDataException("Unexpected action point update layout");
            maxCall.OpCode = OpCodes.Add;
            maxCall.Operand = null;
            var tick = update.Body.GetILProcessor();
            foreach (var instruction in new[] {
                Instruction.Create(OpCodes.Ldloc, updatedBox), Instruction.Create(OpCodes.Ldfld, cap),
                Instruction.Create(OpCodes.Conv_I4), Instruction.Create(OpCodes.Ldloc, updatedBox),
                Instruction.Create(OpCodes.Ldfld, current), Instruction.Create(OpCodes.Conv_I4),
                Instruction.Create(OpCodes.Sub), Instruction.Create(OpCodes.Call, minInt),
            }) tick.InsertBefore(store, instruction);
            loadNow.OpCode = OpCodes.Ldarg_0;
            tick.InsertAfter(loadNow, Instruction.Create(OpCodes.Ldfld, due));
            tick.InsertBefore(add, Instruction.Create(OpCodes.Ldloc, count));
            tick.InsertBefore(add, Instruction.Create(OpCodes.Conv_R8));
            tick.InsertBefore(add, Instruction.Create(OpCodes.Mul));
            assembly.Write(output);
        }
    }

    private static MethodReference MathMethod(TypeReference owner, string name, TypeReference type, int arity)
    {
        var method = new MethodReference(name, type, owner);
        for (int i = 0; i < arity; i++) method.Parameters.Add(new ParameterDefinition(type));
        return method;
    }
}
