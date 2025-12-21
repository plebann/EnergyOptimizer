"""Simple test runner for unit tests without pytest overhead."""
import sys

sys.path.insert(0, "tests")

# Import test modules
import test_energy
import test_battery
import test_charging
import test_heat_pump
import test_utils

def run_tests():
    """Run all unit tests."""
    test_modules = [
        ("Energy Calculations", test_energy, [
            "test_calculate_required_energy",
            "test_calculate_usage_ratio",
            "test_calculate_surplus_energy",
            "test_calculate_energy_deficit",
            "test_calculate_target_soc_for_deficit",
            "test_calculate_required_energy_with_heat_pump",
        ]),
        ("Battery Calculations", test_battery, [
            # Add battery test functions here
        ]),
        ("Charging Calculations", test_charging, [
            # Add charging test functions here
        ]),
        ("Heat Pump Calculations", test_heat_pump, [
            # Add heat pump test functions here  
        ]),
        ("Utilities", test_utils, [
            # Add utility test functions here
        ]),
    ]
    
    total_tests = 0
    passed_tests = 0
    failed_tests = []
    
    for module_name, module, test_functions in test_modules:
        if not test_functions:
            continue
            
        print(f"\n{module_name}:")
        print("-" * 50)
        
        for test_name in test_functions:
            total_tests += 1
            try:
                test_func = getattr(module, test_name)
                test_func()
                print(f"  ✓ {test_name}")
                passed_tests += 1
            except Exception as e:
                print(f"  ✗ {test_name}")
                print(f"    Error: {e}")
                failed_tests.append((module_name, test_name, str(e)))
    
    # Summary
    print("\n" + "=" * 50)
    print(f"Tests run: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {len(failed_tests)}")
    
    if failed_tests:
        print("\nFailed tests:")
        for module_name, test_name, error in failed_tests:
            print(f"  - {module_name}/{test_name}: {error}")
        sys.exit(1)
    else:
        print("\n✓ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    run_tests()
