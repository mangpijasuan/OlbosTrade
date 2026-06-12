/**
 * python_bridge.cpp — pybind11 bridge connecting Python OlbosQuant to C++ engine.
 *
 * This is the integration point. Python calls these functions:
 *
 *   import olbosquant_engine as eng
 *
 *   engine = eng.ExecutionEngine()
 *   engine.start()
 *
 *   # From paper_trader.py run_signal_cycle():
 *   signal = eng.Signal()
 *   signal.type = eng.SignalType.BullPut
 *   signal.signal_score = 0.73
 *   signal.limit_price = 1.25
 *   engine.submit_signal(signal)
 *
 *   # Get result
 *   result = engine.get_last_result()
 *   if result.success:
 *       print(f"Order {result.order_id} dispatched in {result.latency_us}μs")
 *
 *   # Kill switch from Python guardrail engine:
 *   engine.engage_kill_switch()
 *
 * BUILD:
 *   pip install pybind11
 *   c++ -O3 -march=native -std=c++20 -shared -fPIC \
 *       $(python3 -m pybind11 --includes) \
 *       -I../include \
 *       python_bridge.cpp ../src/engine.cpp \
 *       -o olbosquant_engine$(python3-config --extension-suffix)
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "../include/engine.hpp"

namespace py = pybind11;
using namespace olbosquant;

PYBIND11_MODULE(olbosquant_engine, m) {
    m.doc() = "OlbosQuant C++ Execution Engine — Python bridge";

    // ── Enums ──────────────────────────────────────────────────────────────────
    py::enum_<Signal::Type>(m, "SignalType")
        .value("None",       Signal::Type::None)
        .value("BullPut",    Signal::Type::BullPut)
        .value("BearCall",   Signal::Type::BearCall)
        .value("IronCondor", Signal::Type::IronCon)
        .value("BullCall",   Signal::Type::BullCall)
        .value("KillSwitch", Signal::Type::KillSwitch)
        .export_values();

    py::enum_<OrderSide>(m, "OrderSide")
        .value("Buy",  OrderSide::Buy)
        .value("Sell", OrderSide::Sell)
        .export_values();

    py::enum_<Order::Status>(m, "OrderStatus")
        .value("Pending",     Order::Status::Pending)
        .value("Submitted",   Order::Status::Submitted)
        .value("Filled",      Order::Status::Filled)
        .value("Rejected",    Order::Status::Rejected)
        .value("Cancelled",   Order::Status::Cancelled)
        .value("PartialFill", Order::Status::PartialFill)
        .export_values();

    py::enum_<RejectionReason>(m, "RejectionReason")
        .value("None",             RejectionReason::None)
        .value("KillSwitch",       RejectionReason::KillSwitch)
        .value("StaleQuote",       RejectionReason::StaleQuote)
        .value("SpreadTooWide",    RejectionReason::SpreadTooWide)
        .value("SizeTooSmall",     RejectionReason::SizeTooSmall)
        .value("ScoreTooLow",      RejectionReason::ScoreTooLow)
        .value("DailyLossLimit",   RejectionReason::DailyLossLimit)
        .value("TradeCap",         RejectionReason::TradeCap)
        .value("InsufficientEdge", RejectionReason::InsufficientEdge)
        .export_values();

    // ── Signal struct ──────────────────────────────────────────────────────────
    py::class_<Signal>(m, "Signal")
        .def(py::init<>())
        .def_readwrite("type",         &Signal::type)
        .def_readwrite("side",         &Signal::side)
        .def_readwrite("signal_score", &Signal::signal_score)
        .def_readwrite("quantity",     &Signal::quantity)
        // Expose prices as Python floats (convert from fixed-point)
        .def_property(
            "limit_price",
            [](const Signal& s) { return from_price(s.limit_price); },
            [](Signal& s, double v) { s.limit_price = to_price(v); }
        )
        .def_property(
            "short_strike",
            [](const Signal& s) { return from_price(s.short_strike); },
            [](Signal& s, double v) { s.short_strike = to_price(v); }
        )
        .def_property(
            "long_strike",
            [](const Signal& s) { return from_price(s.long_strike); },
            [](Signal& s, double v) { s.long_strike = to_price(v); }
        )
        .def("__repr__", [](const Signal& s) {
            return "<Signal type=" + std::to_string(static_cast<int>(s.type))
                + " score=" + std::to_string(s.signal_score) + ">";
        });

    // ── ExecutionResult struct ─────────────────────────────────────────────────
    py::class_<ExecutionResult>(m, "ExecutionResult")
        .def(py::init<>())
        .def_readonly("success",    &ExecutionResult::success)
        .def_readonly("order_id",   &ExecutionResult::order_id)
        .def_readonly("status",     &ExecutionResult::status)
        .def_readonly("latency_us", &ExecutionResult::latency_us)
        .def_property_readonly("error_msg", [](const ExecutionResult& r) {
            return std::string(r.error_msg);
        })
        .def("__repr__", [](const ExecutionResult& r) {
            return "<ExecutionResult success=" + std::string(r.success ? "True" : "False")
                + " order_id=" + std::to_string(r.order_id)
                + " latency=" + std::to_string(r.latency_us) + "μs>";
        });

    // ── ExecutionEngine ────────────────────────────────────────────────────────
    py::class_<ExecutionEngine>(m, "ExecutionEngine")
        .def(py::init<>())
        .def("start",  &ExecutionEngine::start,
             "Start market data and execution threads")
        .def("stop",   &ExecutionEngine::stop,
             "Stop all threads cleanly")
        .def("submit_signal", &ExecutionEngine::submit_signal_from_python,
             py::arg("signal"),
             "Submit a signal from Python for execution")
        .def("get_last_result", &ExecutionEngine::get_last_result,
             "Get the most recent execution result")
        .def("engage_kill_switch", &ExecutionEngine::engage_kill_switch,
             "Engage the emergency kill switch — halts all order submission immediately")
        .def("set_kill_switch", &ExecutionEngine::set_kill_switch,
             py::arg("engaged"),
             "Set kill switch state (True=engaged, False=reset)")
        .def("set_capital_preservation", &ExecutionEngine::set_capital_preservation,
             py::arg("active"),
             "Enable/disable capital preservation mode (raises signal threshold)")
        .def("set_max_daily_loss", [](ExecutionEngine& e, double loss_dollars) {
             e.set_max_daily_loss(static_cast<int64_t>(loss_dollars * 100));
         }, py::arg("loss_dollars"),
             "Set max daily loss in dollars (converted to cents internally)")
        .def("reset_daily_counters", &ExecutionEngine::reset_daily_counters,
             "Reset daily trade count and P&L — called at midnight")
        .def("avg_dispatch_latency_us", &ExecutionEngine::avg_dispatch_latency_us,
             "Average signal-to-dispatch latency in microseconds")
        .def("last_rejection_reason", [](const ExecutionEngine& e) {
             return e.last_rejection();
         }, "Last signal rejection reason");

    // ── Module-level utilities ─────────────────────────────────────────────────
    m.def("to_price", [](double d) { return to_price(d); },
          "Convert float to fixed-point price (4 decimal places)");
    m.def("from_price", [](Price p) { return from_price(p); },
          "Convert fixed-point price to float");
}
